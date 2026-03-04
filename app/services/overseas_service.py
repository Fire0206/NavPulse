"""
海外市场数据服务
通过新浪财经 API 获取全球主要指数实时行情，为 QDII 基金估值提供数据源

数据源:  新浪财经全球指数接口 (hq.sinajs.cn)
缓存:    TTLCache 60s（海外市场波动较快，缓存时间短）
支持:    纳斯达克/标普500/道琼斯/恒生/日经/DAX/富时100/CAC40 等

格式示例:
  var hq_str_int_nasdaq="纳斯达克,22484.07,99.37,0.44";
  → name=纳斯达克, price=22484.07, change=99.37, pct=0.44
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import aiohttp
from cachetools import TTLCache

logger = logging.getLogger("navpulse.overseas")

# ── 缓存 (60s TTL) ──
_index_cache: TTLCache = TTLCache(maxsize=50, ttl=60)

# ── 新浪海外指数代码映射 ──
# key = 内部标识, value = (新浪代码, 中文名, 交易时段描述)
SINA_INDEX_MAP: dict[str, tuple[str, str, str]] = {
    "nasdaq":   ("int_nasdaq",   "纳斯达克",   "US 21:30-04:00"),
    "sp500":    ("int_sp500",    "标普500",    "US 21:30-04:00"),
    "dji":      ("int_dji",      "道琼斯",     "US 21:30-04:00"),
    "hangseng": ("int_hangseng", "恒生指数",   "HK 09:30-16:00"),
    "nikkei":   ("int_nikkei",   "日经225",    "JP 08:00-14:00"),
    "dax":      ("int_dax",      "德国DAX",    "EU 15:00-23:30"),
    "ftse":     ("int_ftse",     "富时100",    "UK 15:30-00:00"),
    "cac":      ("int_cac",      "法国CAC40",  "EU 15:00-23:30"),
}

# 反向映射: 新浪代码 → 内部标识
_REVERSE_MAP: dict[str, str] = {v[0]: k for k, v in SINA_INDEX_MAP.items()}


async def get_overseas_index_change(benchmark: str) -> dict | None:
    """
    获取单个海外指数的最新涨跌幅

    Args:
        benchmark: 内部标识，如 "nasdaq", "sp500", "hangseng"

    Returns:
        {"name": "纳斯达克", "price": 22484.07, "change_pct": 0.44, ...} 或 None
    """
    if benchmark in _index_cache:
        return {**_index_cache[benchmark], "cached": True}

    info = SINA_INDEX_MAP.get(benchmark)
    if not info:
        logger.warning("未知海外指数标识: %s", benchmark)
        return None

    sina_code = info[0]
    try:
        url = f"https://hq.sinajs.cn/list={sina_code}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                text = await resp.text()
                return _parse_and_cache_single(text, benchmark)
    except asyncio.TimeoutError:
        logger.error("海外指数请求超时 (%s)", benchmark)
    except Exception as e:
        logger.error("获取海外指数失败 (%s): %s", benchmark, e)
    return None


async def get_all_overseas_indices() -> dict[str, dict]:
    """
    批量获取所有已配置的海外指数

    Returns:
        {"nasdaq": {...}, "sp500": {...}, ...}
    """
    all_codes = ",".join(v[0] for v in SINA_INDEX_MAP.values())
    results: dict[str, dict] = {}

    try:
        url = f"https://hq.sinajs.cn/list={all_codes}"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                text = await resp.text()

                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # 提取新浪代码
                    code_match = re.search(r"hq_str_(\w+)=", line)
                    if not code_match:
                        continue
                    sina_code = code_match.group(1)
                    benchmark = _REVERSE_MAP.get(sina_code)
                    if not benchmark:
                        continue
                    parsed = _parse_and_cache_single(line, benchmark)
                    if parsed:
                        results[benchmark] = parsed

    except asyncio.TimeoutError:
        logger.error("批量获取海外指数超时")
    except Exception as e:
        logger.error("批量获取海外指数失败: %s", e)

    return results


def _parse_and_cache_single(raw_line: str, benchmark: str) -> dict | None:
    """解析新浪接口单行响应并写入缓存"""
    match = re.search(r'"(.+?)"', raw_line)
    if not match:
        return None

    parts = match.group(1).split(",")
    if len(parts) < 4:
        return None

    try:
        result = {
            "benchmark": benchmark,
            "name": parts[0],
            "price": float(parts[1]),
            "change_amount": float(parts[2]),
            "change_pct": float(parts[3]),
            "update_time": datetime.now().strftime("%H:%M:%S"),
            "cached": False,
        }
        _index_cache[benchmark] = result
        return result
    except (ValueError, IndexError) as e:
        logger.warning("解析海外指数数据失败 (%s): %s", benchmark, e)
        return None


def get_overseas_cache_info() -> dict:
    """返回海外指数缓存状态"""
    return {
        "size": len(_index_cache),
        "maxsize": _index_cache.maxsize,
        "ttl": _index_cache.ttl,
        "indices": list(_index_cache.keys()),
    }
