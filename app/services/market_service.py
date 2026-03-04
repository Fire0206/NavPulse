"""
行情服务 - 获取大盘指数、涨跌分布、板块数据
使用 akshare 获取实时行情数据，并应用 TTLCache 缓存
"""
from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import akshare as ak
from cachetools import TTLCache

logger = logging.getLogger("navpulse.market")

# ── 全局缓存 ──────────────────────────────────────────────
# 大盘指数缓存 60秒
_index_cache: TTLCache = TTLCache(maxsize=10, ttl=60)
# 涨跌分布缓存 60秒
_distribution_cache: TTLCache = TTLCache(maxsize=10, ttl=60)
# 板块数据缓存 120秒
_sector_cache: TTLCache = TTLCache(maxsize=50, ttl=120)
# 基金涨跌榜缓存 300秒 (数据量大，缓存久一点)
_fund_rank_cache: TTLCache = TTLCache(maxsize=5, ttl=300)
# 全量基金 DataFrame 共享缓存 120秒（涨跌分布 + 涨跌榜共用，避免重复调接口）
_fund_df_cache: TTLCache = TTLCache(maxsize=1, ttl=120)

# 线程池，用于在异步环境中执行同步的 akshare 调用
_executor = ThreadPoolExecutor(max_workers=4)


# ── A/C 类基金去重正则 ──────────────────────────────────
# 匹配基金名称末尾的 A/B/C/D/E 等份额后缀（含前面可能的空格）
_SHARE_CLASS_RE = re.compile(r'[\s]?[A-Ea-e]$')


def _strip_share_class(name: str) -> str:
    """去掉基金名称末尾的份额后缀，返回基准名称"""
    return _SHARE_CLASS_RE.sub('', name).strip()


def _dedup_ac_class(df, name_col: str = "\u57fa\u91d1\u7b80\u79f0"):
    """
    对 DataFrame 执行 A/C 类去重：
    - 同一基准名称下，若存在 C 类则仅保留 C 类
    - 若只有 A 类则保留 A 类
    - 其他不带 A/C 后缀的记录原样保留
    """
    import pandas as pd

    names = df[name_col].astype(str)
    bases = names.apply(_strip_share_class)
    suffixes = names.apply(lambda n: n[-1] if _SHARE_CLASS_RE.search(n) else '')

    df = df.copy()
    df['_base'] = bases
    df['_suffix'] = suffixes

    # 构建每个基准名称下是否存在 C 类的查找表
    has_c = set(df.loc[df['_suffix'].str.upper() == 'C', '_base'].unique())

    # 保留规则：无后缀保留 | 后缀为 C 保留 | 后缀非 C 但该基准名下无 C 类，也保留
    mask = (
        (df['_suffix'] == '') |
        (df['_suffix'].str.upper() == 'C') |
        (~df['_base'].isin(has_c))
    )
    result = df.loc[mask].drop(columns=['_base', '_suffix'])
    return result


def _sync_get_index_data() -> list[dict[str, Any]]:
    """
    同步获取大盘指数数据（上证、深证、创业板）
    主路径：新浪财经 stock_zh_index_spot_sina（无 symbol 参数，一次返回全部）
    备路径：东方财富 stock_zh_index_spot_em（有时被代理拦截）
    """
    # ── 主路径：新浪财经 ─────────────────────────────────
    try:
        df = ak.stock_zh_index_spot_sina()   # 无参数，一次性返回全部指数
        if df is not None and not df.empty:
            _SINA_MAP = {
                "sh000001": ("上证指数", "000001"),
                "sz399001": ("深证成指", "399001"),
                "sz399006": ("创业板指", "399006"),
            }
            result = []
            for sina_code, (name, code) in _SINA_MAP.items():
                sub = df[df["代码"] == sina_code]
                if not sub.empty:
                    row = sub.iloc[0]
                    result.append({
                        "name": name,
                        "code": code,
                        "price": float(row.get("最新价", 0) or 0),
                        "change": float(row.get("涨跌额", 0) or 0),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                    })
            if result:
                return result
    except Exception as e:
        logger.warning(f"[INDEX] 新浪接口失败，切换东方财富: {e}")

    # ── 备路径：东方财富 ─────────────────────────────────
    try:
        result = []
        df_sh = ak.stock_zh_index_spot_em(symbol="上证系列指数")
        sh_index = df_sh[df_sh["代码"] == "000001"]
        if not sh_index.empty:
            row = sh_index.iloc[0]
            result.append({
                "name": "上证指数", "code": "000001",
                "price": float(row.get("最新价", 0)),
                "change": float(row.get("涨跌额", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
            })
        try:
            df_sz = ak.stock_zh_index_spot_em(symbol="深证系列指数")
            for code, name in [("399001", "深证成指"), ("399006", "创业板指")]:
                r = df_sz[df_sz["代码"] == code]
                if not r.empty:
                    row = r.iloc[0]
                    result.append({
                        "name": name, "code": code,
                        "price": float(row.get("最新价", 0)),
                        "change": float(row.get("涨跌额", 0)),
                        "change_pct": float(row.get("涨跌幅", 0)),
                    })
        except Exception as e2:
            logger.warning(f"[INDEX] 深证指数拉取失败: {e2}")
        if result:
            return result
    except Exception as e:
        logger.error(f"获取指数数据失败: {e}")

    # ── 两路都失败：返回空列表（不存入缓存，下次会重试） ──────────
    return []


def _get_all_fund_df():
    """
    获取全量开放式基金 DataFrame（共享缓存）
    涨跌分布 + 涨跌榜共用同一份数据，120秒内只调一次 akshare 接口
    返回已完成 日增长率 数值转换 + A/C 类去重 的 DataFrame
    """
    cache_key = "all_fund_df"
    if cache_key in _fund_df_cache:
        return _fund_df_cache[cache_key]

    df = ak.fund_open_fund_rank_em(symbol="全部")
    if df is None or df.empty:
        raise ValueError("获取基金排行数据为空")

    # 日增长率转数值
    df["日增长率"] = df["日增长率"].apply(
        lambda x: float(x) if x and str(x) not in ("--", "", "None") else 0
    )
    # A/C 类去重
    df = _dedup_ac_class(df, name_col="基金简称")

    _fund_df_cache[cache_key] = df
    logger.info("[DF] 全量基金数据已缓存: %d 只（去重后）", len(df))
    return df


def _sync_get_stock_distribution() -> dict[str, Any]:
    """
    同步获取全市场基金涨跌分布
    使用 _get_all_fund_df() 共享缓存，避免重复调接口
    """
    _empty = {
        "up_count": 0, "down_count": 0, "flat_count": 0, "total": 0,
        "distribution": {
            "down_5": 0, "down_3_5": 0, "down_1_3": 0, "down_0_1": 0,
            "flat": 0,
            "up_0_1": 0, "up_1_3": 0, "up_3_5": 0, "up_5": 0,
        },
    }

    try:
        df = _get_all_fund_df()
        change_col = "日增长率"

        up   = int((df[change_col] > 0).sum())
        down = int((df[change_col] < 0).sum())
        flat = int((df[change_col] == 0).sum())

        distribution = {
            "down_5":   int((df[change_col] <= -5).sum()),
            "down_3_5": int(((df[change_col] > -5)  & (df[change_col] <= -3)).sum()),
            "down_1_3": int(((df[change_col] > -3)  & (df[change_col] <= -1)).sum()),
            "down_0_1": int(((df[change_col] > -1)  & (df[change_col] < 0)).sum()),
            "flat":     flat,
            "up_0_1":   int(((df[change_col] > 0)   & (df[change_col] < 1)).sum()),
            "up_1_3":   int(((df[change_col] >= 1)  & (df[change_col] < 3)).sum()),
            "up_3_5":   int(((df[change_col] >= 3)  & (df[change_col] < 5)).sum()),
            "up_5":     int((df[change_col] >= 5).sum()),
        }

        logger.info("[DIST] 基金涨跌分布: 上涨%d 下跌%d 平盘%d (共%d只)",
                     up, down, flat, up + down + flat)
        return {"up_count": up, "down_count": down, "flat_count": flat,
                "total": up + down + flat, "distribution": distribution}
    except Exception as e:
        logger.error(f"获取基金涨跌分布失败: {e}")
        return _empty


def _sync_get_sector_data() -> list[dict[str, Any]]:
    """
    从数据库读取板块数据（不爬取）
    板块由管理员通过 POST /api/market/sectors 手动维护
    涨跌幅从 global_cache 中各基金当日估值加权平均计算
    """
    from app.database import SessionLocal
    from app.models import Sector
    from app.state import global_cache

    db = SessionLocal()
    try:
        rows = db.query(Sector).order_by(
            Sector.sort_order.desc(), Sector.name
        ).all()
        if not rows:
            return []

        import json
        result = []
        for row in rows:
            codes = json.loads(row.fund_codes or "[]")
            # 计算板块涨跌幅：取该板块所有基金当日估值的简单平均
            changes = []
            for code in codes:
                v = global_cache.get_fund_valuation(code)
                if v and "error" not in v:
                    chg = v.get("estimate_change") or v.get("change_pct") or 0
                    if chg is not None:
                        try:
                            changes.append(float(chg))
                        except (TypeError, ValueError):
                            pass
            change_pct = round(sum(changes) / len(changes), 2) if changes else 0.0
            result.append(row.to_dict(change_pct=change_pct))
        return result
    except Exception as e:
        logger.error(f"读取板块数据失败: {e}")
        return []
    finally:
        db.close()


async def get_market_indices() -> list[dict[str, Any]]:
    """
    异步获取大盘指数（带缓存）
    """
    cache_key = "indices"
    if cache_key in _index_cache:
        return _index_cache[cache_key]
    
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _sync_get_index_data)
    _index_cache[cache_key] = result
    return result


async def get_stock_distribution() -> dict[str, Any]:
    """
    异步获取涨跌分布（带缓存）
    """
    cache_key = "distribution"
    if cache_key in _distribution_cache:
        return _distribution_cache[cache_key]
    
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _sync_get_stock_distribution)
    _distribution_cache[cache_key] = result
    return result


async def get_sector_list() -> list[dict[str, Any]]:
    """
    异步获取板块列表（从 DB 读取，不爬取））
    """
    cache_key = "sectors"
    if cache_key in _sector_cache:
        return _sector_cache[cache_key]
    
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _sync_get_sector_data)
    _sector_cache[cache_key] = result
    return result


def _sync_get_fund_rank() -> dict[str, Any]:
    """
    同步获取基金涨跌榜数据
    使用 _get_all_fund_df() 共享缓存，避免重复调接口
    """
    try:
        df = _get_all_fund_df()

        # \u53d6\u65e5\u671f\u3001\u5355\u4f4d\u51c0\u503c\u4e5f\u8f6c\u4e3a\u5b89\u5168\u7c7b\u578b
        data_date = ""
        if "\u65e5\u671f" in df.columns and not df.empty:
            data_date = str(df.iloc[0]["\u65e5\u671f"]) if df.iloc[0]["\u65e5\u671f"] else ""

        def _row_to_dict(row):
            nav = row.get("\u5355\u4f4d\u51c0\u503c", 0)
            return {
                "code": str(row.get("\u57fa\u91d1\u4ee3\u7801", "")),
                "name": str(row.get("\u57fa\u91d1\u7b80\u79f0", "")),
                "daily_change": float(row.get("\u65e5\u589e\u957f\u7387", 0)),
                "nav": float(nav) if nav and str(nav) not in ("--", "") else 0,
            }

        # \u6d28\u5e45\u699c TOP 50
        top_df = df.nlargest(50, "\u65e5\u589e\u957f\u7387")
        top_list = [_row_to_dict(row) for _, row in top_df.iterrows()]

        # \u8dcc\u5e45\u699c TOP 50
        bottom_df = df.nsmallest(50, "\u65e5\u589e\u957f\u7387")
        bottom_list = [_row_to_dict(row) for _, row in bottom_df.iterrows()]

        return {
            "date": data_date,
            "top": top_list,
            "bottom": bottom_list,
            "total_count": len(df),
        }
    except Exception as e:
        logger.error(f"\u83b7\u53d6\u57fa\u91d1\u6d28\u8dcc\u699c\u5931\u8d25: {e}")
        return {"date": "", "top": [], "bottom": [], "total_count": 0}


def _is_valid_fund_rank(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    top = data.get("top") or []
    bottom = data.get("bottom") or []
    return bool(top or bottom)


def _load_fund_rank_from_db() -> dict[str, Any] | None:
    """从 SQLite 读取上次可用的基金涨跌榜缓存"""
    try:
        import json
        from app.database import SessionLocal
        from app.models import CachedData

        db = SessionLocal()
        try:
            row = db.query(CachedData).filter(CachedData.key == "fund_rank").first()
            if not row or not row.value:
                return None
            data = json.loads(row.value)
            if _is_valid_fund_rank(data):
                return data
            return None
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"读取基金涨跌榜持久化缓存失败: {e}")
        return None


def _persist_fund_rank_to_db(data: dict[str, Any]):
    """将基金涨跌榜写入 SQLite（用于重启后秒开）"""
    if not _is_valid_fund_rank(data):
        return
    try:
        import json
        from datetime import datetime
        from app.database import SessionLocal
        from app.models import CachedData

        db = SessionLocal()
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = db.query(CachedData).filter(CachedData.key == "fund_rank").first()
            payload = json.dumps(data, ensure_ascii=False)
            if row:
                row.value = payload
                row.updated_at = now
            else:
                db.add(CachedData(key="fund_rank", value=payload, updated_at=now))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"持久化基金涨跌榜失败: {e}")


async def _fetch_fund_rank_fresh(timeout_seconds: int = 12) -> dict[str, Any]:
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, _sync_get_fund_rank),
            timeout=timeout_seconds,
        )
    except Exception as e:
        logger.warning(
            "实时拉取基金涨跌榜失败/超时: %s (%s)",
            str(e) or "no-detail",
            type(e).__name__,
        )
        return {"date": "", "top": [], "bottom": [], "total_count": 0}


async def get_fund_rank(force_refresh: bool = False) -> dict[str, Any]:
    """
    异步获\u53d6\u57fa\u91d1\u6d28\u8dcc\u699c\uff08\u5e26\u7f13\u5b58\uff09
    """
    cache_key = "fund_rank"
    if not force_refresh and cache_key in _fund_rank_cache:
        return _fund_rank_cache[cache_key]

    # 非强刷：优先返回 SQLite 中最近一次可用数据，保证页面秒开
    if not force_refresh:
        db_cached = _load_fund_rank_from_db()
        if _is_valid_fund_rank(db_cached):
            _fund_rank_cache[cache_key] = db_cached
            return db_cached

    result = await _fetch_fund_rank_fresh(timeout_seconds=12)
    if _is_valid_fund_rank(result):
        _fund_rank_cache[cache_key] = result
        _persist_fund_rank_to_db(result)
        return result

    # 拉取失败兜底：内存缓存 → SQLite → 空结构
    if cache_key in _fund_rank_cache:
        return _fund_rank_cache[cache_key]
    db_cached = _load_fund_rank_from_db()
    if _is_valid_fund_rank(db_cached):
        _fund_rank_cache[cache_key] = db_cached
        return db_cached
    return {"date": "", "top": [], "bottom": [], "total_count": 0}


async def get_full_market_data() -> dict[str, Any]:
    """
    获取完整的行情数据（指数 + 涨跌分布 + 板块）
    并行获取以提升性能
    """
    indices, distribution, sectors = await asyncio.gather(
        get_market_indices(),
        get_stock_distribution(),
        get_sector_list(),
    )
    
    return {
        "indices": indices,
        "distribution": distribution,
        "sectors": sectors,
    }


def get_market_cache_info() -> dict[str, Any]:
    """获取行情缓存信息"""
    return {
        "index_cache_size": len(_index_cache),
        "distribution_cache_size": len(_distribution_cache),
        "sector_cache_size": len(_sector_cache),
        "fund_rank_cache_size": len(_fund_rank_cache),
        "fund_df_cache_size": len(_fund_df_cache),
    }


def clear_market_cache():
    """清空行情缓存"""
    _index_cache.clear()
    _distribution_cache.clear()
    _sector_cache.clear()
    _fund_rank_cache.clear()
    _fund_df_cache.clear()
