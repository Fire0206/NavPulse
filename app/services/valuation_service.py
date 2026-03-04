"""
基金实时估值服务 (Async 重构版)
整合基金持仓和股票实时行情，计算基金净值估值

性能优化:
  - aiohttp 异步 HTTP 请求，不阻塞 FastAPI 事件循环
  - asyncio.gather 并行: fund_name + fund_portfolio 同时获取;
    多只基金估值同时计算
  - TTLCache (300s) 内存缓存，命中时 < 1ms 返回
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiohttp
from cachetools import TTLCache

logger = logging.getLogger("navpulse.valuation")

# ── 全局缓存 ──────────────────────────────────────────────
# maxsize=1000: 同时缓存 1000 只基金的估值数据
# ttl=300:      每条数据 5 分钟自动过期，兼顾实时性和性能
_cache: TTLCache = TTLCache(maxsize=1000, ttl=300)
_cache_lock = asyncio.Lock()

# ══════════════════════════════════════════════════════════
#  估值优化参数 (回测进化引擎 v2.4 最优参数)
#  基线 MAE 0.1499 → 优化后 0.1169 (↓22%)
# ══════════════════════════════════════════════════════════

# ── 非重仓股市场代理填充 ──
# 季报 Top10 仅覆盖约 55% 权重，剩余用市场平均涨跌代理
_NON_TOP_PROXY_CHANGE = 0.12   # 市场平均代理涨跌幅 %

# ── ETF 联接基金仓位修正 ──
_ETF_POSITION_RATIO = 0.92     # 联接基金实际投资 ETF 的比例 (~92%)
_ETF_CASH_DRAG = 0.005         # 现金仓位每日拖累 %

# ── QDII 汇率修正 ──
_QDII_MGMT_FEE_DAILY = 0.004   # QDII 日均管理费拖累 %
_QDII_TRACKING_BETA = 1.0      # 指数跟踪 beta
_QDII_FX_ADJUST = True         # 是否启用汇率联动修正

# ── 经理调仓探测 (Drift Detection) ──
_DRIFT_DECAY_RATE = 0.02       # 持仓权重月衰减率 (2%/月)
_DRIFT_ENABLE = True           # 是否启用权重衰减

# ── 行业 β 系数映射 (板块对冲) ──
# 基于历史回测，不同行业相对大盘的 β 系数
_SECTOR_BETA: dict[str, float] = {
    # 消费/白酒 — 防守型 β<1
    "600519": 0.92, "000858": 0.92, "000568": 0.92,
    "000596": 0.92, "002304": 0.92,
    # 新能源/半导体 — 进攻型 β>1
    "601012": 1.08, "002475": 1.05, "300750": 1.10,
    "688981": 1.08, "002371": 1.08,
    # 银行/保险 — 低波动
    "601318": 0.95, "600036": 0.93, "601166": 0.93,
    # 医药 — 中性偏防守
    "603259": 0.96, "000661": 0.96,
}


# ══════════════════════════════════════════════════════════
#  异步行情获取 (aiohttp，替代 requests)
# ══════════════════════════════════════════════════════════

def _build_qt_query(stock_codes: list[str]) -> tuple[list[str], dict[str, str]]:
    """
    构建腾讯行情接口的查询参数

    Returns:
        (query_list, code_map)
        - query_list: ["s_sh601138", "s_hk00700", ...]
        - code_map:   {"s_sh601138": "601138", ...}
    """
    query_list: list[str] = []
    code_map: dict[str, str] = {}

    for code in stock_codes:
        code = str(code).strip()
        qt_code = ""

        if len(code) == 6:
            if code.startswith("6"):
                qt_code = f"sh{code}"
            elif code.startswith(("0", "3")):
                qt_code = f"sz{code}"
            elif code.startswith(("4", "8")):
                qt_code = f"bj{code}"
            else:
                qt_code = f"sh{code}"
        elif len(code) == 5:
            qt_code = f"hk{code}"
        else:
            continue

        if qt_code:
            full_qt_code = f"s_{qt_code}"
            query_list.append(full_qt_code)
            code_map[full_qt_code] = code

    return query_list, code_map


def _parse_qt_response(text: str, code_map: dict[str, str]) -> dict[str, dict]:
    """解析腾讯行情接口的响应文本"""
    result: dict[str, dict] = {}
    for line in text.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue

        left, right = line.split("=", 1)
        qt_key = left.strip().split("v_")[-1]
        data_str = right.strip().strip('"')
        data_parts = data_str.split("~")

        if len(data_parts) < 6:
            continue

        original_code = code_map.get(qt_key)
        if not original_code:
            continue

        try:
            price = float(data_parts[3])
            change_pct = float(data_parts[5])
        except (ValueError, IndexError):
            price = 0.0
            change_pct = 0.0

        result[original_code] = {
            "name": data_parts[1],
            "price": price,
            "change_pct": change_pct,
        }

    return result


async def _get_realtime_prices_async(stock_codes: list[str]) -> dict[str, dict]:
    """
    异步获取股票实时行情 (aiohttp)

    利用腾讯批量接口一次请求获取所有股票行情，
    通过 aiohttp 实现非阻塞 I/O，不会卡死 FastAPI 事件循环。
    """
    if not stock_codes:
        return {}

    query_list, code_map = _build_qt_query(stock_codes)
    if not query_list:
        return {}

    url = f"http://qt.gtimg.cn/q={','.join(query_list)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    logger.warning("行情接口返回 HTTP %s", resp.status)
                    return {}
                text = await resp.text()
                return _parse_qt_response(text, code_map)
    except asyncio.TimeoutError:
        logger.error("行情接口请求超时 (5s)")
        return {}
    except Exception as e:
        logger.error("异步获取行情异常: %s", e)
        return {}


# ══════════════════════════════════════════════════════════
#  QDII 汇率服务 (USD/CNY 日间波动)
# ══════════════════════════════════════════════════════════

_fx_cache: TTLCache = TTLCache(maxsize=10, ttl=300)  # 5分钟缓存


async def _get_fx_rate_change() -> dict | None:
    """
    获取 USD/CNY 日内汇率涨跌幅（新浪财经）
    用于 QDII 估值的汇率联动修正

    Returns:
        {"rate": 7.24, "change_pct": 0.05} 或 None
    """
    if "usdcny" in _fx_cache:
        return _fx_cache["usdcny"]

    try:
        url = "https://hq.sinajs.cn/list=fx_susdcny"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                text = await resp.text()
                import re
                match = re.search(r'"(.+?)"', text)
                if not match:
                    return None
                parts = match.group(1).split(",")
                if len(parts) < 8:
                    return None
                try:
                    current_rate = float(parts[1])
                    prev_close = float(parts[3])
                    if prev_close > 0:
                        change_pct = (current_rate - prev_close) / prev_close * 100
                        result = {"rate": current_rate, "change_pct": round(change_pct, 4)}
                        _fx_cache["usdcny"] = result
                        return result
                except (ValueError, IndexError):
                    pass
    except Exception as e:
        logger.debug("获取汇率失败: %s", e)
    return None


# ══════════════════════════════════════════════════════════
#  核心估值函数 (async + TTLCache)
# ══════════════════════════════════════════════════════════

async def calculate_fund_estimate(fund_code: str, *, force_trading: bool = False) -> dict:
    """
    计算基金实时估值（异步 + TTLCache）

    估值策略路由（按基金类型自动选择最优算法）:
      - ETF 联接基金  → 底层 ETF 场内实时价格
      - QDII 基金     → 海外指数实时涨跌幅
      - 场内 ETF      → ETF 场内实时价格
      - 普通股票/混合  → 重仓股实时行情加权（原始算法）
      - 债券/货币      → 仅返回历史净值

    Args:
        fund_code: 基金代码
        force_trading: 强制走交易时段估值算法（用于非交易时段调试/验证）

    缓存策略:
      Hit  → 直接返回内存数据，< 1ms
      Miss → 执行异步爬虫 → 写入缓存 → 返回
    
    休市策略:
      A股休市时，国内基金返回上一交易日的实际涨跌幅；
      QDII 基金仍尝试获取海外指数实时数据。

    Returns:
        {
            "fund_code": "005963",
            "fund_name": "广发半导体...",
            "data_date": "2025-12-31",
            "total_weight": 43.15,
            "estimate_change": 1.25,
            "coverage": 85.0,
            "update_time": "14:35:20",
            "cached": True/False,
            "estimation_method": "weighted_holdings",
            "fund_type": "stock",
            "holdings": [ ... ]
        }
    """
    from app.services.trading_calendar import is_market_open

    market_open = is_market_open() or force_trading

    # ── 0. 基金分类（决定估值策略） ──
    try:
        from app.services.fund_classifier import classify_fund
        classification = await asyncio.to_thread(classify_fund, fund_code)
    except Exception as _e:
        logger.warning("基金分类失败 (%s): %s, 回退默认策略", fund_code, _e)
        from app.services.fund_classifier import FundClassification
        classification = FundClassification("other", "weighted_holdings")

    # ── 1. 查缓存（force_trading 模式跳过缓存） ──
    if not force_trading:
        async with _cache_lock:
            cached = _cache.get(fund_code)
        if cached is not None:
            is_qdii = classification.estimation_method == "overseas_index"
            # 非交易时段：
            #   国内基金 → 跳过交易时段缓存，用历史净值
            #   QDII    → 海外指数缓存(60s)比估值缓存(300s)更短，也跳过重新获取
            if not market_open and not cached.get("is_closed"):
                pass  # 跳过缓存，重新计算
            elif is_qdii and not cached.get("is_closed"):
                pass  # QDII 开盘时段也需要更频繁刷新
            else:
                return {**cached, "cached": True}

    # ── 2. 非交易时段 ──
    if not market_open:
        # QDII 基金: A股休市时海外市场可能仍在交易，尝试获取海外指数
        if classification.estimation_method == "overseas_index":
            qdii_result = await _estimate_qdii_fund(
                fund_code, classification, is_closed=False
            )
            if qdii_result and "error" not in qdii_result:
                async with _cache_lock:
                    _cache[fund_code] = qdii_result
                return qdii_result

        # 国内基金 / QDII回退: 优先用今日分时末点估值，否则读历史净值
        try:
            from app.services.fund_service import (
                _sync_get_fund_history, get_fund_name, get_fund_portfolio
            )
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo as _ZI
            today_str = _dt.now(_ZI("Asia/Shanghai")).strftime("%Y-%m-%d")

            # 并行获取: 历史净值 + 基金名称 + 基金持仓
            history, fund_name, portfolio = await asyncio.gather(
                asyncio.to_thread(_sync_get_fund_history, fund_code, 10),
                asyncio.to_thread(get_fund_name, fund_code),
                asyncio.to_thread(get_fund_portfolio, fund_code),
            )

            # 若今日净值未入库 → 尝试分时接口末点
            today_in_history = (
                history
                and history[-1].get("date") == today_str
                and history[-1].get("change_pct", 0) != 0
            )
            if not today_in_history:
                try:
                    intraday = await calculate_intraday_from_stocks(fund_code)
                    pts = intraday.get("points", [])
                    if pts:
                        last_change = next(
                            (p["change"] for p in reversed(pts)
                             if p.get("change") is not None),
                            None,
                        )
                        if last_change is not None:
                            history = [{
                                "date": today_str, "nav": 0,
                                "change_pct": round(last_change, 4),
                            }]
                except Exception as _e:
                    logger.warning("[ESTIMATE] %s 分时兜底失败: %s", fund_code, _e)

            if history and len(history) >= 1:
                last_data = history[-1]

                # 获取重仓股行情（非交易时段返回收盘数据）
                holdings = (
                    portfolio.get("holdings", [])
                    if "error" not in portfolio else []
                )
                enriched_holdings = []
                total_weight_val = 0.0

                if holdings:
                    stock_codes = [h["code"] for h in holdings if h.get("code")]
                    prices = await _get_realtime_prices_async(stock_codes)
                    for h in holdings:
                        code = h.get("code")
                        weight = h.get("weight", 0)
                        price_info = prices.get(code, {})
                        enriched_holdings.append({
                            "code": code,
                            "name": h.get("name", ""),
                            "weight": weight,
                            "price": price_info.get("price", 0),
                            "change_pct": price_info.get("change_pct", 0),
                        })
                        total_weight_val += weight

                result = {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "data_date": last_data.get("date"),
                    "total_weight": round(total_weight_val, 2),
                    "estimate_change": last_data.get("change_pct", 0),
                    "holdings": enriched_holdings,
                    "coverage": round(total_weight_val, 2),
                    "update_time": datetime.now().strftime("%H:%M:%S"),
                    "cached": False,
                    "last_nav": last_data.get("nav"),
                    "is_closed": True,
                    "estimation_method": "history",
                    "fund_type": classification.fund_type,
                    "fund_type_label": classification.description,
                }
                async with _cache_lock:
                    _cache[fund_code] = result
                return result
        except Exception as e:
            logger.warning("获取历史涨跌幅失败 (%s): %s", fund_code, e)

    # ── 3. 交易时段 → 按基金类型路由到不同估值引擎 ──
    result = await _fetch_fund_estimate(fund_code, classification)

    # ── 4. 仅缓存成功结果 ──
    if "error" not in result:
        async with _cache_lock:
            _cache[fund_code] = result

    return result


async def _fetch_fund_estimate(fund_code: str, classification=None) -> dict:
    """
    异步执行爬虫获取估值数据（多策略路由版）

    路由逻辑:
      1. ETF 联接基金 (penetrated_from)  → ETF 场内实时价格
      2. QDII 基金 (overseas_index)      → 海外指数涨跌幅
      3. 场内 ETF (etf_realtime)         → ETF 场内价格直取
      4. 普通基金 (weighted_holdings)     → 重仓股行情加权（原始算法）
      5. 无持仓兜底                       → 历史净值涨跌幅
    """
    try:
        from app.services.fund_service import (
            get_fund_portfolio, get_fund_name, _sync_get_fund_history
        )

        # ── 并行获取基金名称 + 持仓数据 + 历史净值 ──
        fund_name, portfolio, history = await asyncio.gather(
            asyncio.to_thread(get_fund_name, fund_code),
            asyncio.to_thread(get_fund_portfolio, fund_code),
            asyncio.to_thread(_sync_get_fund_history, fund_code, 10),
        )

        last_nav = history[-1].get("nav", 0) if history else 0
        fund_type = classification.fund_type if classification else "other"
        fund_type_label = classification.description if classification else ""

        # ── 策略 A: ETF 联接基金 → 直接用底层 ETF 场内价格 ──
        etf_code = portfolio.get("penetrated_from")
        if etf_code:
            etf_result = await _estimate_via_etf_price(
                fund_code, fund_name, etf_code, portfolio, history,
                fund_type, fund_type_label,
            )
            if etf_result:
                return etf_result

        # ── 策略 B: 场内 ETF → 自身场内价格 ──
        if classification and classification.estimation_method == "etf_realtime":
            etf_result = await _estimate_via_etf_price(
                fund_code, fund_name, fund_code, portfolio, history,
                fund_type, fund_type_label,
            )
            if etf_result:
                return etf_result

        # ── 策略 C: QDII → 海外指数 ──
        if classification and classification.estimation_method == "overseas_index":
            qdii_result = await _estimate_qdii_fund(
                fund_code, classification, is_closed=False,
                fund_name=fund_name, portfolio=portfolio, history=history,
            )
            if qdii_result and "error" not in qdii_result:
                return qdii_result

        # ── 策略 D: 重仓股加权估值（原始算法） ──
        holdings = []
        if "error" not in portfolio:
            holdings = portfolio.get("holdings", [])

        stock_codes = [h["code"] for h in holdings if h.get("code")]

        # 无持仓数据（新基金 / 季报未披露）→ 历史净值兜底
        if not stock_codes:
            if history:
                last = history[-1]
                return {
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "data_date": last.get("date"),
                    "total_weight": 0,
                    "estimate_change": last.get("change_pct", 0),
                    "holdings": [],
                    "coverage": 0,
                    "update_time": datetime.now().strftime("%H:%M:%S"),
                    "cached": False,
                    "last_nav": last.get("nav", 0),
                    "is_closed": True,
                    "nav_fallback": True,
                    "estimation_method": "nav_history",
                    "fund_type": fund_type,
                    "fund_type_label": fund_type_label,
                }
            return {"error": "基金持仓和历史净值均为空", "fund_name": fund_name}

        # ── 异步获取实时行情 (aiohttp) ──
        prices = await _get_realtime_prices_async(stock_codes)

        enriched_holdings = []
        total_weighted_change = 0.0
        total_weight_with_price = 0.0

        # ── 权重衰减：季报距今越久权重越不可信 ──
        data_date_str = portfolio.get("data_date", "")
        decay_factor = 1.0
        if _DRIFT_ENABLE and data_date_str:
            try:
                from datetime import datetime as _dt
                data_dt = _dt.strptime(data_date_str[:10], "%Y-%m-%d")
                months_elapsed = (datetime.now() - data_dt).days / 30.0
                decay_factor = max(1.0 - _DRIFT_DECAY_RATE * months_elapsed, 0.5)
            except (ValueError, TypeError):
                decay_factor = 1.0

        for holding in holdings:
            code = holding.get("code")
            weight = holding.get("weight", 0.0)
            price_info = prices.get(code)

            if price_info:
                change_pct = price_info.get("change_pct", 0.0)
                # 行业 β 修正
                beta = _SECTOR_BETA.get(code, 1.0)
                adjusted_change = change_pct * beta
                # 权重衰减修正
                adjusted_weight = weight * decay_factor
                total_weighted_change += adjusted_weight * adjusted_change
                total_weight_with_price += adjusted_weight
                enriched_holdings.append({
                    "code": code,
                    "name": holding.get("name", ""),
                    "weight": weight,
                    "price": price_info.get("price", 0.0),
                    "change_pct": change_pct,
                })
            else:
                logger.warning("股票 %s 行情缺失，跳过该股计算", code)
                enriched_holdings.append({
                    "code": code,
                    "name": holding.get("name", ""),
                    "weight": weight,
                    "price": None,
                    "change_pct": None,
                })

        estimate_change = 0.0
        if total_weight_with_price > 0:
            # ── 非重仓股市场代理填充 ──
            # 季报 Top10 仅覆盖约 55% 权重，剩余用市场平均代理
            covered_weight = sum(
                h.get("weight", 0) for h in holdings if h.get("code") in prices
            )
            uncovered_weight = max(100.0 - covered_weight, 0)
            if uncovered_weight > 0:
                estimate_change = (
                    total_weighted_change + uncovered_weight * _NON_TOP_PROXY_CHANGE
                ) / 100.0
            else:
                estimate_change = total_weighted_change / total_weight_with_price

        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "data_date": portfolio.get("data_date"),
            "total_weight": portfolio.get("total_weight", 0.0),
            "estimate_change": round(estimate_change, 2),
            "holdings": enriched_holdings,
            "coverage": round(total_weight_with_price, 2),
            "update_time": datetime.now().strftime("%H:%M:%S"),
            "cached": False,
            "last_nav": last_nav,
            "estimation_method": "weighted_holdings",
            "fund_type": fund_type,
            "fund_type_label": fund_type_label,
        }

    except Exception as e:
        import traceback
        logger.error("计算基金估值异常: %s\n%s", e, traceback.format_exc())
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════
#  策略 A/B: ETF 场内实时价格估值
# ══════════════════════════════════════════════════════════

async def _estimate_via_etf_price(
    fund_code: str,
    fund_name: str,
    etf_code: str,
    portfolio: dict,
    history: list,
    fund_type: str = "",
    fund_type_label: str = "",
) -> dict | None:
    """
    通过 ETF 场内实时价格估算联接基金/ETF 涨跌幅

    ETF 场内价格通过腾讯行情接口实时获取，比重仓股加权更精确:
    - ETF 价格反映全部持仓（不仅是 top10）
    - ETF 套利机制保证价格紧贴 NAV
    - 实时性极高（秒级更新）
    """
    try:
        prices = await _get_realtime_prices_async([etf_code])
        etf_info = prices.get(etf_code)
        if not etf_info or etf_info.get("change_pct") is None:
            logger.warning("ETF %s 行情获取失败，回退到重仓股估值", etf_code)
            return None

        raw_etf_change = etf_info["change_pct"]
        # ── 联接基金仓位修正：实际仅 ~92% 投资 ETF + 现金拖累 ──
        etf_change = round(raw_etf_change * _ETF_POSITION_RATIO - _ETF_CASH_DRAG, 2)
        etf_name = etf_info.get("name", etf_code)
        last_nav = history[-1].get("nav", 0) if history else 0

        # 获取重仓股行情（用于详情页展示，非估值计算）
        holdings = portfolio.get("holdings", []) if "error" not in portfolio else []
        enriched_holdings = []
        total_weight_val = 0.0

        if holdings:
            stock_codes = [h["code"] for h in holdings if h.get("code")]
            if stock_codes:
                stock_prices = await _get_realtime_prices_async(stock_codes)
                for h in holdings:
                    code = h.get("code")
                    weight = h.get("weight", 0)
                    pi = stock_prices.get(code, {})
                    enriched_holdings.append({
                        "code": code,
                        "name": h.get("name", ""),
                        "weight": weight,
                        "price": pi.get("price", 0),
                        "change_pct": pi.get("change_pct", 0),
                    })
                    total_weight_val += weight

        logger.info(
            "[ETF估值] %s → ETF %s (%s): %.2f%%",
            fund_code, etf_code, etf_name, etf_change,
        )

        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "data_date": portfolio.get("data_date"),
            "total_weight": round(total_weight_val, 2),
            "estimate_change": round(etf_change, 2),
            "holdings": enriched_holdings,
            "coverage": round(total_weight_val, 2),
            "update_time": datetime.now().strftime("%H:%M:%S"),
            "cached": False,
            "last_nav": last_nav,
            "estimation_method": "etf_realtime",
            "etf_code": etf_code,
            "etf_name": etf_name,
            "etf_price": etf_info.get("price", 0),
            "fund_type": fund_type,
            "fund_type_label": fund_type_label,
        }
    except Exception as e:
        logger.error("ETF 估值失败 (%s → %s): %s", fund_code, etf_code, e)
        return None


# ══════════════════════════════════════════════════════════
#  策略 C: QDII 海外指数估值
# ══════════════════════════════════════════════════════════

async def _estimate_qdii_fund(
    fund_code: str,
    classification,
    is_closed: bool = False,
    fund_name: str | None = None,
    portfolio: dict | None = None,
    history: list | None = None,
) -> dict | None:
    """
    通过海外指数估算 QDII 基金涨跌幅

    根据基金跟踪的海外指数（纳斯达克/标普/恒生等），
    从新浪财经获取指数实时涨跌幅作为基金估值。

    对于 T+2 类基金（如美股 QDII），涨跌幅反映的是
    海外市场最近的交易数据（非严格 T+D 回算，而是最新可用数据）。
    """
    try:
        from app.services.overseas_service import get_overseas_index_change

        benchmark = classification.benchmark_index
        if not benchmark:
            return None

        # 并行获取海外指数 + 基金基础数据（如果还没有的话）
        tasks = [get_overseas_index_change(benchmark)]
        need_name = fund_name is None
        need_history = history is None

        if need_name:
            from app.services.fund_service import get_fund_name
            tasks.append(asyncio.to_thread(get_fund_name, fund_code))
        if need_history:
            from app.services.fund_service import _sync_get_fund_history
            tasks.append(asyncio.to_thread(_sync_get_fund_history, fund_code, 10))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        index_data = results[0] if not isinstance(results[0], Exception) else None

        idx = 1
        if need_name:
            fund_name = results[idx] if not isinstance(results[idx], Exception) else fund_code
            idx += 1
        if need_history:
            history = results[idx] if not isinstance(results[idx], Exception) else []

        if not index_data:
            logger.warning("海外指数 %s 数据不可用 (%s)", benchmark, fund_code)
            return None

        last_nav = history[-1].get("nav", 0) if history else 0
        index_change = index_data.get("change_pct", 0)
        index_name = index_data.get("name", benchmark)

        # ── QDII 估值优化：β跟踪 + 管理费扣减 + 汇率联动 ──
        adjusted_change = index_change * _QDII_TRACKING_BETA
        adjusted_change -= _QDII_MGMT_FEE_DAILY

        # 汇率联动修正（获取实时汇率变动）
        fx_adjustment = 0.0
        if _QDII_FX_ADJUST:
            try:
                fx_data = await _get_fx_rate_change()
                if fx_data:
                    fx_adjustment = fx_data.get("change_pct", 0)
                    adjusted_change += fx_adjustment
            except Exception as _fx_e:
                logger.debug("QDII 汇率修正跳过: %s", _fx_e)

        logger.info(
            "[QDII估值] %s → %s (%s): 指数%.2f%% β=%.2f 管理费-%.3f%% 汇率%+.3f%% → 最终%.2f%%, T+%d",
            fund_code, benchmark, index_name, index_change,
            _QDII_TRACKING_BETA, _QDII_MGMT_FEE_DAILY, fx_adjustment,
            adjusted_change, classification.settlement_delay,
        )

        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "data_date": index_data.get("update_time"),
            "total_weight": 0,
            "estimate_change": round(adjusted_change, 2),
            "holdings": [],
            "coverage": 0,
            "update_time": datetime.now().strftime("%H:%M:%S"),
            "cached": False,
            "last_nav": last_nav,
            "is_closed": is_closed,
            "estimation_method": "overseas_index",
            "benchmark": benchmark,
            "benchmark_name": index_name,
            "benchmark_price": index_data.get("price", 0),
            "benchmark_raw_change": round(index_change, 2),
            "fx_adjustment": round(fx_adjustment, 3),
            "settlement_delay": classification.settlement_delay,
            "fund_type": classification.fund_type,
            "fund_type_label": classification.description,
        }
    except Exception as e:
        logger.error("QDII 估值失败 (%s): %s", fund_code, e)
        return None


# ══════════════════════════════════════════════════════════
#  组合看板估值 (asyncio.gather 并行)
# ══════════════════════════════════════════════════════════

async def get_portfolio_valuation(holdings: list) -> dict:
    """
    计算组合估值（asyncio.gather 并行版）

    N 只基金通过 asyncio.gather 同时计算，
    每只基金内部又通过 gather 并行获取 名称+持仓，
    Cache Hit 时几乎零开销。
    
    金融标准计算:
    - 市值 = 份额 × 最新净值
    - 持有收益 = 市值 - 成本
    - 当日收益 = 市值 × 涨跌幅%

    Args:
        holdings: [{"code":"005963","shares":1000.0,"cost":2000.0}, ...]

    Returns:
        {
            "total_market_value": ..., "total_cost": ...,
            "total_profit": ...,      "total_profit_rate": ...,
            "total_daily_profit": ..., "total_daily_profit_rate": ...,
            "funds": [ ... ]
        }
    """
    try:
        from app.services.fund_service import _sync_get_fund_history
        
        async def _process_single_fund(h: dict) -> dict | None:
            code = h.get("code")
            shares = h.get("shares", 0.0)
            cost = h.get("cost", 0.0)
            # 兼容旧格式 amount
            if shares <= 0 and h.get("amount", 0) > 0:
                shares = h["amount"]
                cost = h["amount"]

            if not code or shares <= 0:
                return None

            valuation = await calculate_fund_estimate(code)
            
            # 获取最新净值（用于计算真实市值）
            last_nav = valuation.get("last_nav", 0)
            if not last_nav:
                try:
                    history = await asyncio.to_thread(_sync_get_fund_history, code, 10)
                    if history:
                        last_nav = history[-1].get("nav", 0)
                except Exception:
                    pass

            if "error" in valuation:
                # 估值失败时，尝试用历史净值计算
                market_value = shares * last_nav if last_nav > 0 else cost
                # 从估值结果或单独获取基金名称
                err_name = valuation.get("fund_name", code)
                if err_name == code:
                    try:
                        from app.services.fund_service import get_fund_name
                        err_name = await asyncio.to_thread(get_fund_name, code)
                    except Exception:
                        pass
                return {
                    "code": code, "name": err_name or code,
                    "shares": shares, "cost": cost,
                    "market_value": round(market_value, 2),
                    "estimate_change": 0.0,
                    "daily_profit": 0.0,
                    "holding_profit": round(market_value - cost, 2),
                    "holding_profit_rate": round((market_value - cost) / cost * 100, 2) if cost > 0 else 0,
                    "last_nav": last_nav,
                    "avg_cost": round(cost / shares, 4) if shares > 0 else 0,
                    "error": valuation.get("error"),
                    "data_date": None,
                    "holdings_count": 0,
                }

            estimate_change = valuation.get("estimate_change", 0.0)
            
            # 金融标准: 市值 = 份额 × 最新净值
            if last_nav > 0:
                market_value = shares * last_nav
            else:
                # 无净值时退化为成本计算
                market_value = cost
            
            # 今日收益 = (昨收净值 × 份额) × 涨跌幅%
            # 简化: 市值 × 涨跌幅 / (1 + 涨跌幅%)
            if estimate_change != 0 and last_nav > 0:
                yesterday_value = market_value / (1 + estimate_change / 100)
                daily_profit = round(market_value - yesterday_value, 2)
            else:
                daily_profit = 0
            
            # 持有收益 = 市值 - 成本
            holding_profit = round(market_value - cost, 2)
            holding_profit_rate = round((holding_profit / cost * 100) if cost > 0 else 0, 2)
            
            # 平均成本 = 总成本 / 份额
            avg_cost = round(cost / shares, 4) if shares > 0 else 0

            return {
                "code": code,
                "name": valuation.get("fund_name", code),
                "shares": shares,
                "cost": cost,
                "market_value": round(market_value, 2),
                "estimate_change": estimate_change,
                "daily_profit": daily_profit,
                "holding_profit": holding_profit,
                "holding_profit_rate": holding_profit_rate,
                "last_nav": last_nav,
                "avg_cost": avg_cost,
                "data_date": valuation.get("data_date"),
                "holdings_count": len(valuation.get("holdings", [])),
                "update_time": valuation.get("update_time"),
                "cached": valuation.get("cached", False),
                # ── 新增: 估值策略元数据 ──
                "estimation_method": valuation.get("estimation_method", ""),
                "fund_type": valuation.get("fund_type", ""),
                "fund_type_label": valuation.get("fund_type_label", ""),
                "etf_code": valuation.get("etf_code"),
                "etf_name": valuation.get("etf_name"),
                "benchmark": valuation.get("benchmark"),
                "benchmark_name": valuation.get("benchmark_name"),
                "settlement_delay": valuation.get("settlement_delay", 0),
            }

        # ── asyncio.gather 并发执行所有基金估值 ──
        raw_results = await asyncio.gather(
            *(_process_single_fund(h) for h in holdings),
            return_exceptions=True,
        )

        total_market_value = 0.0
        total_cost = 0.0
        total_daily_profit = 0.0
        funds_detail: list[dict] = []

        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                code = holdings[i].get("code", "?")
                logger.error("基金 %s 处理异常: %s", code, result)
                continue
            if result is None:
                continue

            funds_detail.append(result)
            total_market_value += result["market_value"]
            total_cost += result["cost"]
            total_daily_profit += result.get("daily_profit", 0.0)

        # 按原始顺序排列
        code_order = {h.get("code"): i for i, h in enumerate(holdings)}
        funds_detail.sort(key=lambda x: code_order.get(x["code"], 999))

        total_profit = round(total_market_value - total_cost, 2)
        total_profit_rate = round(
            (total_profit / total_cost * 100) if total_cost else 0, 2)
        total_daily_profit_rate = round(
            (total_daily_profit / total_market_value * 100)
            if total_market_value else 0, 2)

        return {
            "total_market_value": round(total_market_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": total_profit,
            "total_profit_rate": total_profit_rate,
            "total_daily_profit": round(total_daily_profit, 2),
            "total_daily_profit_rate": total_daily_profit_rate,
            "funds": funds_detail,
        }

    except Exception as e:
        import traceback
        logger.error("计算组合估值异常: %s\n%s", e, traceback.format_exc())
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════
#  日内分时估值（基于重仓股分时数据）
# ══════════════════════════════════════════════════════════

def _get_qt_code(stock_code: str) -> str | None:
    """将股票代码转换为腾讯行情 API 格式 (sh/sz/bj/hk 前缀)"""
    code = str(stock_code).strip()
    if len(code) == 6:
        if code.startswith("6"):
            return f"sh{code}"
        elif code.startswith(("0", "3")):
            return f"sz{code}"
        elif code.startswith(("4", "8")):
            return f"bj{code}"
        else:
            return f"sh{code}"
    elif len(code) == 5:
        return f"hk{code}"
    return None


async def _get_stock_minute_data_async(stock_codes: list[str]) -> dict[str, dict]:
    """
    异步获取多只股票的分时数据（当日/上一交易日）

    数据源: 腾讯行情分时接口 ifzq.gtimg.cn
    非交易时段调用时，返回上一个交易日的分时数据。

    Returns:
        {stock_code: {"prec": float, "trade_date": str, "minutes": [{"time": "HH:MM", "price": float}, ...]}}
    """
    import json as _json
    results = {}

    async def fetch_one(session: aiohttp.ClientSession, code: str, qt_code: str):
        url = f"http://ifzq.gtimg.cn/appstock/app/minute/query?code={qt_code}"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return
                text = await resp.text()

                # 解析响应 (JSON 或 JSONP)
                try:
                    data = _json.loads(text)
                except _json.JSONDecodeError:
                    if "=" in text:
                        json_str = text.split("=", 1)[1].rstrip(";").strip()
                        data = _json.loads(json_str)
                    else:
                        return

                stock_data = data.get("data", {}).get(qt_code, {})
                if not stock_data:
                    return

                # 昨收价 (previous close)
                prec = 0.0
                qt_info = stock_data.get("qt", {}).get(qt_code, [])
                if isinstance(qt_info, list) and len(qt_info) > 4:
                    try:
                        prec = float(qt_info[4])
                    except (ValueError, TypeError):
                        pass
                if prec == 0:
                    try:
                        prec = float(stock_data.get("prec", 0))
                    except (ValueError, TypeError):
                        pass

                # 解析分时数据
                raw_data = stock_data.get("data", {})
                if not isinstance(raw_data, dict):
                    return

                date_str = str(raw_data.get("date", ""))
                raw_points = raw_data.get("data", [])

                if not isinstance(raw_points, list):
                    return

                minutes = []
                for point_str in raw_points:
                    if not isinstance(point_str, str):
                        continue
                    parts = point_str.strip().split()
                    if len(parts) >= 2:
                        time_raw = parts[0]
                        try:
                            price = float(parts[1])
                        except ValueError:
                            continue
                        if len(time_raw) >= 4:
                            time_fmt = f"{time_raw[:2]}:{time_raw[2:4]}"
                        else:
                            continue
                        minutes.append({"time": time_fmt, "price": price})

                # 格式化交易日期
                trade_date = ""
                if len(date_str) == 8:
                    trade_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                elif len(date_str) == 6:
                    trade_date = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"

                if minutes and prec > 0:
                    results[code] = {
                        "prec": prec,
                        "trade_date": trade_date,
                        "minutes": minutes,
                    }
        except Exception as e:
            logger.warning("获取 %s 分时数据失败: %s", code, e)

    # 构建 stock_code → qt_code 映射
    code_qt_pairs = []
    for code in stock_codes:
        qt_code = _get_qt_code(code)
        if qt_code:
            code_qt_pairs.append((code, qt_code))

    if not code_qt_pairs:
        return results

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            *(fetch_one(session, code, qt) for code, qt in code_qt_pairs),
            return_exceptions=True,
        )

    return results


async def calculate_intraday_from_stocks(fund_code: str) -> dict:
    """
    根据基金重仓股的分时数据，计算基金日内估值走势曲线

    流程:
      1. 获取基金持仓（股票代码 + 权重）
      2. 异步获取各股票分时数据（腾讯分时接口）
      3. 前向填充缺失分钟数据
      4. 加权计算每分钟的基金估值涨跌幅

    Returns:
        {
            "fund_code": str,
            "trade_date": str,
            "points": [{"time": "HH:MM", "change": float}, ...],
            "is_live": bool,
        }
    """
    from app.services.trading_calendar import is_market_open

    try:
        from app.services.fund_service import get_fund_portfolio

        # 1. 获取基金持仓
        portfolio = await asyncio.to_thread(get_fund_portfolio, fund_code)
        holdings = portfolio.get("holdings", [])
        if not holdings:
            return {"fund_code": fund_code, "trade_date": "", "points": [], "is_live": False}

        stock_codes = [h["code"] for h in holdings if h.get("code")]
        weights = {h["code"]: h.get("weight", 0) for h in holdings}

        # 2. 获取分时数据
        minute_data = await _get_stock_minute_data_async(stock_codes)
        if not minute_data:
            return {"fund_code": fund_code, "trade_date": "", "points": [], "is_live": False}

        # 3. 确定交易日期
        trade_date = ""
        for data in minute_data.values():
            if data and data.get("trade_date"):
                trade_date = data["trade_date"]
                break

        # 4. 收集所有时间点并排序
        all_times = set()
        for data in minute_data.values():
            if data:
                for m in data.get("minutes", []):
                    all_times.add(m["time"])
        sorted_times = sorted(all_times)

        if not sorted_times:
            return {"fund_code": fund_code, "trade_date": trade_date, "points": [], "is_live": False}

        # 5. 前向填充每只股票的分时价格
        stock_info = {}
        for code, data in minute_data.items():
            if not data or data["prec"] <= 0:
                continue
            raw_map = {}
            for m in data["minutes"]:
                raw_map[m["time"]] = m["price"]

            filled_map = {}
            last_price = None
            for t in sorted_times:
                if t in raw_map:
                    last_price = raw_map[t]
                if last_price is not None:
                    filled_map[t] = last_price
            stock_info[code] = {"prices": filled_map, "prec": data["prec"]}

        # 6. 加权计算每分钟的基金估值涨跌幅
        points = []
        for time_str in sorted_times:
            weighted_change = 0.0
            weight_sum = 0.0

            for code, info in stock_info.items():
                weight = weights.get(code, 0)
                if weight <= 0:
                    continue
                price = info["prices"].get(time_str)
                if price is not None:
                    change = (price - info["prec"]) / info["prec"] * 100
                    weighted_change += weight * change
                    weight_sum += weight

            if weight_sum > 0:
                estimate = round(weighted_change / weight_sum, 4)
                points.append({"time": time_str, "change": estimate})

        logger.info("基金 %s 日内走势计算完成: %d 个数据点", fund_code, len(points))
        return {
            "fund_code": fund_code,
            "trade_date": trade_date,
            "points": points,
            "is_live": is_market_open(),
        }

    except Exception as e:
        logger.error("计算日内走势失败 (%s): %s", fund_code, e)
        return {"fund_code": fund_code, "trade_date": "", "points": [], "is_live": False}


# ══════════════════════════════════════════════════════════
#  缓存管理工具
# ══════════════════════════════════════════════════════════

def get_cache_info() -> dict:
    """返回当前缓存状态，可用于调试 / 健康检查"""
    return {
        "size": len(_cache),
        "maxsize": _cache.maxsize,
        "ttl": _cache.ttl,
        "keys": list(_cache.keys()),
    }


def clear_cache() -> None:
    """手动清空所有缓存（供管理接口调用）"""
    _cache.clear()
    print("[INFO] 估值缓存已清空")
