"""
基金相关路由
处理基金估值、详情、历史净值、日内走势、交易记录
"""
import asyncio
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import User, IntradayEstimate
from app.schemas import TransactionRequest
from app.services.auth_service import get_current_user
from app.services.fund_service import (
    get_fund_name,
    get_fund_history_async,
    get_fund_portfolio,
    _sync_get_fund_history,
    _db_get_portfolio,
    _db_get_history_latest_nav,
)
from app.services.valuation_service import (
    calculate_fund_estimate,
    _get_realtime_prices_async,
    _get_stock_minute_data_async,
)
from app.services.trading_calendar import is_market_open, is_trading_day
from app.state import global_cache

router = APIRouter(tags=["基金"])


# ==================== 基金估值 ====================

# 后台估值刷新锁（per fund_code）
_bg_valuation_locks: set[str] = set()


async def _background_valuation_refresh(fund_code: str):
    """后台静默刷新单只基金估值（不阻塞 API）"""
    if fund_code in _bg_valuation_locks:
        return
    _bg_valuation_locks.add(fund_code)
    try:
        result = await calculate_fund_estimate(fund_code)
        if "error" not in result:
            global_cache.update_fund_valuation(fund_code, result)
            logger.info("[BG-VAL] %s 后台估值刷新完成", fund_code)
    except Exception as e:
        logger.warning("[BG-VAL] %s 后台估值刷新失败: %s", fund_code, e)
    finally:
        _bg_valuation_locks.discard(fund_code)


@router.get("/api/valuation/{fund_code}")
async def get_fund_valuation(fund_code: str, force_refresh: bool = False):
    """
    单只基金估值 API（也用于穿透模态框）
    始终立即返回缓存数据；缓存缺失时触发后台计算。
    force_refresh=true 时也触发后台刷新，但仍立即返回当前缓存。
    """
    cached = global_cache.get_fund_valuation(fund_code)

    if force_refresh:
        # 触发后台刷新，但立即返回当前缓存
        asyncio.create_task(_background_valuation_refresh(fund_code))
        return cached or {"fund_code": fund_code, "estimate_change": 0, "_pending": True}

    if cached:
        return cached

    # 完全无缓存（新基金首次打开）→ 触发后台计算，返回空壳
    asyncio.create_task(_background_valuation_refresh(fund_code))
    return {"fund_code": fund_code, "estimate_change": 0, "_pending": True}


# ==================== 基金历史净值 ====================

@router.get("/api/fund/history/{fund_code}")
async def get_fund_history(fund_code: str, days: int = 90):
    """获取基金历史净值数据"""
    try:
        if not fund_code or len(fund_code) != 6:
            raise HTTPException(status_code=400,
                                detail="基金代码格式错误，应为6位数字")
        result = await get_fund_history_async(fund_code, days)
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail=f"获取历史净值失败: {str(e)}")


# ==================== 交易记录 ====================

@router.get("/api/fund/{fund_code}/transactions")
async def get_fund_transactions(
    fund_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取某基金的持仓统计 + 全部交易记录"""
    from app.services.transaction_service import calculate_holding_stats
    return calculate_holding_stats(db, current_user.id, fund_code)


@router.post("/api/fund/{fund_code}/transactions")
async def add_fund_transaction(
    fund_code: str,
    req: TransactionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    添加交易记录（自动同步 Holding 表）
    支持 type = "init" / "buy" / "sell"
    如果未提供 shares，会自动根据金额和当日净值计算
    """
    from app.services.transaction_service import add_transaction
    from app.services.fund_service import get_nav_on_date

    shares = req.shares
    nav = req.nav

    if shares <= 0 and req.amount > 0:
        if nav <= 0:
            nav = get_nav_on_date(fund_code, req.date)
        if nav > 0:
            shares = round(req.amount / nav, 2)
        else:
            raise HTTPException(status_code=400, detail="无法获取净值，请手动输入份额")

    result = add_transaction(
        db, current_user.id, fund_code,
        req.type, req.date, shares, req.amount, nav,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    global_cache.clear_portfolio_cache(current_user.id)
    return result


@router.delete("/api/fund/{fund_code}/transactions/{tx_id}")
async def delete_fund_transaction(
    fund_code: str,
    tx_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除交易记录（自动同步 Holding 表）"""
    from app.services.transaction_service import delete_transaction
    result = delete_transaction(db, current_user.id, tx_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    global_cache.clear_portfolio_cache(current_user.id)
    return result


# ==================== 日内估值快照 ====================

def _build_trading_minutes() -> list[str]:
    """返回完整交易分钟列表：09:30-11:30, 13:00-15:00"""
    minutes = []
    for h in range(9, 12):
        start = 30 if h == 9 else 0
        end   = 31 if h == 11 else 60
        for m in range(start, end):
            minutes.append(f"{h:02d}:{m:02d}")
    for h in range(13, 15):
        for m in range(0, 60):
            minutes.append(f"{h:02d}:{m:02d}")
    minutes.append("15:00")
    return minutes


def _densify_intraday_points(points: list[dict], up_to: str | None = None) -> list[dict]:
    """
    将稀疏分钟点位前向填充为连续分钟序列，减少图表断点。
    - 仅在已有历史点之后前向填充，不会伪造开盘前未知数据。
    - up_to: 仅输出该时刻及之前分钟（用于交易时段）。
    """
    if not points:
        return []

    minutes = _build_trading_minutes()
    if up_to:
        minutes = [m for m in minutes if m <= up_to]

    point_map = {
        p.get("time"): p.get("change")
        for p in points
        if p.get("time") and p.get("change") is not None
    }

    dense: list[dict] = []
    last_val = None
    for m in minutes:
        if m in point_map:
            last_val = point_map[m]
        if last_val is not None:
            dense.append({"time": m, "change": round(float(last_val), 4)})

    return dense


async def _backfill_intraday_gaps(
    fund_code: str, trade_date: str, existing_points: list, up_to: str | None = None
) -> int:
    """
    检测当日日内数据缺口，从重仓股分时接口回补并写入 DB。
    仅当缺口 >= 3 分钟时才触发网络请求。
    up_to: 只补该时刻及之前的点（交易时段传入当前时间，避免补未来分钟）

    Returns: 实际补充的点数量
    """
    from app.services.fund_service import get_fund_portfolio

    all_minutes = _build_trading_minutes()
    existing_times = {p["time"] for p in existing_points}
    missing = [t for t in all_minutes if t not in existing_times]
    if up_to:
        missing = [t for t in missing if t <= up_to]

    if len(missing) < 3:
        return 0

    logger.info("[BACKFILL] %s 缺 %d 个分钟快照，开始回补…", fund_code, len(missing))

    # ── 获取持仓 + 分时行情 ──
    try:
        portfolio = await asyncio.to_thread(get_fund_portfolio, fund_code)
    except Exception as e:
        logger.warning("[BACKFILL] 获取持仓失败: %s", e)
        return 0

    holdings = portfolio.get("holdings", [])
    if not holdings:
        return 0

    stock_codes = [h["code"] for h in holdings if h.get("code")]
    weights     = {h["code"]: h.get("weight", 0.0) for h in holdings}

    try:
        minute_data = await _get_stock_minute_data_async(stock_codes)
    except Exception as e:
        logger.warning("[BACKFILL] 获取分时数据失败: %s", e)
        return 0

    if not minute_data:
        return 0

    # ── 前向填充各股票价格 ──
    stock_prices: dict[str, dict[str, float]] = {}
    for code, data in minute_data.items():
        if not data or data.get("prec", 0) <= 0:
            continue
        raw_map: dict[str, float] = {m["time"]: m["price"] for m in data["minutes"]}
        filled: dict[str, float] = {}
        last_price = None
        for t in all_minutes:
            if t in raw_map:
                last_price = raw_map[t]
            if last_price is not None:
                filled[t] = last_price
        stock_prices[code] = {"prices": filled, "prec": data["prec"]}

    # ── 逐分钟计算缺失估值并写入 DB ──
    sdb = SessionLocal()
    filled_count = 0
    try:
        for time_str in missing:
            weighted = 0.0
            w_sum    = 0.0
            for code, info in stock_prices.items():
                w = weights.get(code, 0.0)
                if w <= 0:
                    continue
                price = info["prices"].get(time_str)
                if price is not None and info["prec"] > 0:
                    weighted += w * (price - info["prec"]) / info["prec"] * 100
                    w_sum    += w

            if w_sum < 30:           # 覆盖率 < 30% 的分钟跳过
                continue

            est = round(weighted / w_sum, 4)

            # upsert
            row = sdb.query(IntradayEstimate).filter(
                IntradayEstimate.fund_code   == fund_code,
                IntradayEstimate.trade_date  == trade_date,
                IntradayEstimate.time        == time_str,
            ).first()
            if row:
                row.estimate_change = est
            else:
                sdb.add(IntradayEstimate(
                    fund_code=fund_code, trade_date=trade_date,
                    time=time_str, estimate_change=est,
                ))
            filled_count += 1

        sdb.commit()
        logger.info("[BACKFILL] %s 回补完成，共写入 %d 条", fund_code, filled_count)
    except Exception as e:
        sdb.rollback()
        logger.error("[BACKFILL] 写入失败: %s", e)
        filled_count = 0
    finally:
        sdb.close()

    return filled_count


@router.get("/api/fund/{fund_code}/intraday")
async def get_fund_intraday(fund_code: str):
    """
    获取基金日内估值走势
    - 交易时段: 直接从腾讯分时接口计算完整当日曲线（无断点），同时保存当前分钟快照到 DB
    - 非交易时段: 从 DB 读取快照，自动回补缺口；DB 无数据时回退到分时接口计算
    """
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    from app.services.valuation_service import calculate_intraday_from_stocks

    now       = dt.now(ZoneInfo("Asia/Shanghai"))
    today_str = now.strftime("%Y-%m-%d")
    is_live   = is_market_open()
    now_hm    = now.strftime("%H:%M")

    # ── 确定目标日期 ──
    target_date = today_str
    if not is_trading_day(now):
        for i in range(1, 11):
            d = now - timedelta(days=i)
            if is_trading_day(d):
                target_date = d.strftime("%Y-%m-%d")
                break

    # ── 0. 日级别估值基金不应伪造分时曲线（例如 nav_history/history） ──
    valuation_hint = global_cache.get_fund_valuation(fund_code)
    if not valuation_hint:
        try:
            valuation_hint = await calculate_fund_estimate(fund_code)
        except Exception:
            valuation_hint = None

    if valuation_hint and valuation_hint.get("estimation_method") in {"nav_history", "history"}:
        # 仅当确实没有分钟级数据来源时才禁用实时走势。
        # 对于已成功穿透到底层 ETF/重仓的联接基金，仍可计算分钟曲线。
        try:
            portfolio_hint = await asyncio.to_thread(get_fund_portfolio, fund_code)
        except Exception:
            portfolio_hint = {}

        if not (portfolio_hint.get("holdings") and len(portfolio_hint.get("holdings", [])) > 0):
            return {
                "fund_code": fund_code,
                "trade_date": target_date,
                "is_live": False,
                "points": [],
                "no_intraday": True,
                "reason": "nav_history_only",
            }

    # ── 1. 优先从 DB 读取已有快照（毫秒级） ──
    def _load_points(date: str) -> list:
        sdb = SessionLocal()
        try:
            rows = (
                sdb.query(IntradayEstimate)
                .filter(
                    IntradayEstimate.fund_code   == fund_code,
                    IntradayEstimate.trade_date  == date,
                )
                .order_by(IntradayEstimate.time.asc())
                .all()
            )
            return [{"time": r.time, "change": r.estimate_change} for r in rows]
        finally:
            sdb.close()

    db_points = await asyncio.to_thread(_load_points, target_date)

    # ── 1.1 尝试回补 DB 缺口（此前函数存在但未调用，导致长期断点） ──
    if db_points:
        try:
            filled = await asyncio.wait_for(
                _backfill_intraday_gaps(
                    fund_code,
                    target_date,
                    db_points,
                    up_to=now_hm if is_live else None,
                ),
                timeout=8,
            )
            if filled > 0:
                db_points = await asyncio.to_thread(_load_points, target_date)
        except Exception as e:
            logger.warning("[INTRADAY] %s 回补超时/失败: %s", fund_code, e)

    # ── 1.2 DB 无数据时，直接计算完整分时曲线并落库（非交易时段也生效） ──
    if not db_points:
        try:
            fresh = await asyncio.wait_for(calculate_intraday_from_stocks(fund_code), timeout=10)
            fresh_points = fresh.get("points", []) if fresh else []
            if fresh_points:
                save_date = fresh.get("trade_date") or target_date

                def _upsert_points(date: str, points: list[dict]):
                    sdb = SessionLocal()
                    try:
                        for p in points:
                            time_str = p.get("time")
                            change = p.get("change")
                            if not time_str or change is None:
                                continue
                            row = sdb.query(IntradayEstimate).filter(
                                IntradayEstimate.fund_code == fund_code,
                                IntradayEstimate.trade_date == date,
                                IntradayEstimate.time == time_str,
                            ).first()
                            if row:
                                row.estimate_change = change
                            else:
                                sdb.add(IntradayEstimate(
                                    fund_code=fund_code,
                                    trade_date=date,
                                    time=time_str,
                                    estimate_change=change,
                                ))
                        sdb.commit()
                    except Exception:
                        sdb.rollback()
                        raise
                    finally:
                        sdb.close()

                await asyncio.to_thread(_upsert_points, save_date, fresh_points)
                target_date = save_date
                db_points = await asyncio.to_thread(_load_points, target_date)
        except Exception as e:
            logger.warning("[INTRADAY] %s DB空数据兜底计算失败: %s", fund_code, e)

    # ── 2. 后台异步刷新分时数据（不阻塞返回） ──
    async def _bg_refresh_intraday():
        """后台计算完整分时曲线并存储快照"""
        try:
            result = await calculate_intraday_from_stocks(fund_code)
            if not result or not result.get("points"):
                return
            # 同时保存估值快照
            if is_market_open():
                try:
                    val = await calculate_fund_estimate(fund_code)
                    if "error" not in val:
                        est_change = val.get("estimate_change", 0)
                        coverage = val.get("coverage", 0)
                        if coverage >= 30:
                            time_str = now.strftime("%H:%M")
                            sdb = SessionLocal()
                            try:
                                row = sdb.query(IntradayEstimate).filter(
                                    IntradayEstimate.fund_code  == fund_code,
                                    IntradayEstimate.trade_date == today_str,
                                    IntradayEstimate.time       == time_str,
                                ).first()
                                if row:
                                    row.estimate_change = est_change
                                else:
                                    sdb.add(IntradayEstimate(
                                        fund_code=fund_code, trade_date=today_str,
                                        time=time_str, estimate_change=est_change,
                                    ))
                                sdb.commit()
                            finally:
                                sdb.close()
                except Exception as e:
                    logger.warning("[INTRADAY-BG] 快照存储失败: %s", e)
        except Exception as e:
            logger.warning("[INTRADAY-BG] 后台分时计算失败: %s", e)

    # 交易时段或 DB 无数据时触发后台刷新
    if is_live:
        asyncio.create_task(_bg_refresh_intraday())

    # ── 3. 返回分钟级连续数据（减少断点） ──
    points_out = _densify_intraday_points(db_points, up_to=now_hm if is_live else None)

    return {
        "fund_code":  fund_code,
        "trade_date": target_date,
        "is_live":    is_live,
        "points":     points_out,
    }


# ==================== 基金详情综合 ====================

@router.get("/api/fund/{fund_code}/detail")
async def get_fund_detail(
    fund_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    基金详情综合接口: 基金估值 + 用户持仓统计 + 交易记录
    供详情页 header 展示

    性能优化:
      1. DB 数据优先: 持仓统计、历史净值、重仓缓存全从 DB 读取，< 10ms
      2. asyncio.gather 并行: 估值 / 持仓统计 / 净值 / 重仓 同时查询
      3. 缓存优先: 估值先查内存缓存 → 再异步计算
      4. 所有同步函数通过 asyncio.to_thread 卸载，不阻塞事件循环
    """
    from app.services.transaction_service import calculate_holding_stats

    # ── 第一阶段: 全部并行 — DB 查询 + 缓存读取 ──
    async def _get_stats():
        return await asyncio.to_thread(calculate_holding_stats, db, current_user.id, fund_code)

    async def _get_nav():
        data = await asyncio.to_thread(_db_get_history_latest_nav, fund_code)
        return data

    async def _get_portfolio_cache():
        return await asyncio.to_thread(_db_get_portfolio, fund_code)

    async def _get_fund_name_cached():
        return await asyncio.to_thread(get_fund_name, fund_code)

    async def _get_valuation_fast():
        """缓存优先的估值: 内存缓存 → DB 数据兜底 → 异步计算"""
        cached = global_cache.get_fund_valuation(fund_code)
        if cached:
            return cached, False  # (valuation, needs_refresh)
        # 无缓存时仍然尝试计算，但在第二阶段异步进行
        return None, True

    # 并行执行所有快速查询
    stats, last_nav, portfolio_cache, fund_name_val, (valuation_fast, needs_valuation) = \
        await asyncio.gather(
            _get_stats(), _get_nav(), _get_portfolio_cache(),
            _get_fund_name_cached(), _get_valuation_fast(),
        )

    # ── 第二阶段: 估值（缓存优先，无缓存则返回空壳 + 后台刷新） ──
    valuation = valuation_fast
    if needs_valuation:
        # 无缓存 → 返回空壳数据，同时后台异步计算（不阻塞本接口）
        valuation = {"fund_code": fund_code, "estimate_change": 0,
                     "holdings": [], "fund_name": fund_code}
        asyncio.create_task(_background_valuation_refresh(fund_code))

    # 优先使用估值返回的名称
    val_name = valuation.get("fund_name", "")
    if val_name and val_name != fund_code:
        fund_name_val = val_name
    elif fund_name_val == fund_code:
        fund_name_val = fund_code  # 最终兜底

    # ── 重仓股处理 ──
    stocks = valuation.get("holdings", []) or []
    if not stocks and portfolio_cache:
        stocks = portfolio_cache.get("holdings", []) or []

    # 补齐重仓股实时涨跌幅（仅交易时段需要）
    if stocks and is_market_open():
        missing_price = any(s.get("change_pct") is None for s in stocks)
        if missing_price:
            try:
                stock_codes = [s["code"] for s in stocks if s.get("code")]
                prices = await _get_realtime_prices_async(stock_codes)
                for s in stocks:
                    price_info = prices.get(s.get("code"), {})
                    if s.get("change_pct") is None:
                        s["change_pct"] = price_info.get("change_pct", 0)
                        s["price"] = price_info.get("price", 0)
            except Exception:
                pass

    # ── 计算持仓金额、收益等 ──
    total_shares = stats.get("total_shares", 0)
    total_cost = stats.get("total_cost", 0)
    avg_cost = stats.get("avg_cost_per_share", 0)
    estimate_change = valuation.get("estimate_change", 0)

    # 最新净值: 估值接口 > DB 查询
    nav = valuation.get("last_nav", 0) or last_nav or 0

    # 金融标准: 市值 = 份额 × 最新净值
    if nav > 0 and total_shares > 0:
        market_value = total_shares * nav
    else:
        market_value = total_cost * (1 + estimate_change / 100) if total_cost > 0 else 0

    # 今日收益
    if estimate_change != 0 and market_value > 0:
        yesterday_value = market_value / (1 + estimate_change / 100)
        daily_profit = round(market_value - yesterday_value, 2)
    else:
        daily_profit = 0

    # 持有收益 = 市值 - 成本
    holding_profit = round(market_value - total_cost, 2)
    holding_profit_rate = round(holding_profit / total_cost * 100, 2) if total_cost > 0 else 0

    # 持仓占比
    portfolio = global_cache.get_portfolio(current_user.id)
    total_portfolio_value = portfolio.get("total_market_value", 0) if portfolio else 0
    position_ratio = round(market_value / total_portfolio_value * 100, 2) if total_portfolio_value > 0 else 0

    return {
        "fund_code": fund_code,
        "fund_name": fund_name_val,
        "estimate_change": estimate_change,
        "data_date": valuation.get("data_date"),
        "update_time": valuation.get("update_time"),
        "is_closed": valuation.get("is_closed", False),
        "last_nav": nav,
        # 估值策略元数据
        "estimation_method": valuation.get("estimation_method", ""),
        "fund_type": valuation.get("fund_type", ""),
        "fund_type_label": valuation.get("fund_type_label", ""),
        "etf_code": valuation.get("etf_code"),
        "etf_name": valuation.get("etf_name"),
        "benchmark": valuation.get("benchmark"),
        "benchmark_name": valuation.get("benchmark_name"),
        "settlement_delay": valuation.get("settlement_delay", 0),
        # 持仓统计
        "has_holding": stats.get("has_holding", False),
        "total_shares": total_shares,
        "total_cost": total_cost,
        "avg_cost_per_share": avg_cost,
        "market_value": round(market_value, 2),
        "daily_profit": daily_profit,
        "holding_profit": holding_profit,
        "holding_profit_rate": holding_profit_rate,
        "position_ratio": position_ratio,
        "holding_days": stats.get("holding_days", 0),
        # 重仓股
        "stocks": stocks,
        "portfolio_updated_at": (portfolio_cache or {}).get("updated_at", ""),
        # 交易记录
        "transactions": stats.get("transactions", []),
    }
