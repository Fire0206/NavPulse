"""
后台调度器 - 使用 APScheduler 定时刷新行情和估值数据
将数据写入 app.state.global_cache，API 直接读取（秒级响应）
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.state import global_cache
from app.services.market_service import (
    get_market_indices,
    get_stock_distribution,
    get_sector_list,
    get_fund_rank,
)
from app.services.valuation_service import calculate_fund_estimate
from app.services.portfolio_service import get_portfolio_with_valuation_async
from app.services.trading_calendar import is_market_open, get_trading_status
from app.services.fund_service import (
    batch_update_all_tracked_funds,
    batch_fill_all_gaps,
    save_today_estimate_navs,
    update_official_navs,
)
from app.database import SessionLocal
from app.models import User, Holding, Watchlist

logger = logging.getLogger("navpulse.scheduler")

# 全局调度器实例
scheduler: AsyncIOScheduler | None = None


async def _update_market_data_impl():
    """行情数据实际爬取逻辑（无交易时段判断，供多处调用）"""
    logger.info("[INFO] 开始更新行情数据...")
    try:
        indices, distribution = await asyncio.gather(
            get_market_indices(),
            get_stock_distribution(),
            return_exceptions=True,
        )

        if isinstance(indices, Exception):
            logger.error(f"获取指数失败: {indices}")
            indices = global_cache.market_indices or []
        # 如果返回空列表（API全部失败），保留旧缓存中有效的数据
        if not indices and global_cache.market_indices:
            valid_cached = [i for i in global_cache.market_indices if i.get("price")]
            if valid_cached:
                indices = valid_cached
        if isinstance(distribution, Exception):
            logger.error(f"获取涨跌分布失败: {distribution}")
            distribution = global_cache.stock_distribution or {}

        sectors = await get_sector_list()

        global_cache.update_market_data(
            indices=indices,
            distribution=distribution,
            sectors=sectors,
        )

        logger.info(f"[OK] 行情数据更新完成: {len(indices)} 指数, {len(sectors)} 板块")
    except Exception as e:
        logger.error(f"[ERROR] 更新行情数据异常: {e}")


async def update_market_data():
    """
    更新行情数据（大盘指数 + 涨跌分布 + 板块）
    非交易时段跳过（由调度器定时调用）
    """
    if not is_market_open():
        return
    await _update_market_data_impl()


async def update_fund_valuations():
    """
    更新所有用户关注的基金估值
    同时在交易时段存储日内估值快照（供分时走势图使用）
    """
    logger.info("开始更新基金估值...")
    try:
        db = SessionLocal()
        try:
            # 获取所有需要更新的基金代码（持仓 + 自选）
            holding_codes = set(
                h.code for h in db.query(Holding.code).distinct().all()
            )
            watchlist_codes = set(
                w.fund_code for w in db.query(Watchlist.fund_code).distinct().all()
            )
            all_codes = holding_codes | watchlist_codes
            
            if not all_codes:
                logger.info("暂无需要更新的基金")
                return
            
            logger.info(f"需要更新 {len(all_codes)} 只基金估值")
            
            # 批量并行获取估值（限制并发数避免请求过多）
            semaphore = asyncio.Semaphore(5)  # 最多 5 个并发
            
            async def fetch_valuation(code: str):
                async with semaphore:
                    try:
                        result = await calculate_fund_estimate(code)
                        # ★ 不将 error 结果写入缓存，避免污染
                        if "error" not in result:
                            global_cache.update_fund_valuation(code, result)

                        # ★ 交易时段自动存储日内快照
                        if is_market_open() and "error" not in result:
                            _store_intraday_snapshot(
                                code, result.get("estimate_change", 0)
                            )

                        return code, True
                    except Exception as e:
                        logger.warning(f"基金 {code} 估值失败: {e}")
                        return code, False
            
            tasks = [fetch_valuation(code) for code in all_codes]
            results = await asyncio.gather(*tasks)
            
            success_count = sum(1 for _, ok in results if ok)
            logger.info(f"[OK] 基金估值更新完成: {success_count}/{len(all_codes)} 成功")
            
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[ERROR] 更新基金估值异常: {e}")


def _store_intraday_snapshot(fund_code: str, estimate_change: float):
    """存储日内估值快照到数据库（供分时走势图使用）"""
    from app.models import IntradayEstimate
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    now = dt.now(ZoneInfo("Asia/Shanghai"))
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    sdb = SessionLocal()
    try:
        existing = sdb.query(IntradayEstimate).filter(
            IntradayEstimate.fund_code == fund_code,
            IntradayEstimate.trade_date == today_str,
            IntradayEstimate.time == time_str,
        ).first()
        if existing:
            existing.estimate_change = estimate_change
        else:
            sdb.add(IntradayEstimate(
                fund_code=fund_code, trade_date=today_str,
                time=time_str, estimate_change=estimate_change,
            ))
        sdb.commit()
    except Exception as e:
        sdb.rollback()
        logger.warning(f"存储日内快照失败 {fund_code}: {e}")
    finally:
        sdb.close()


async def update_user_portfolios():
    """
    更新所有用户的持仓组合数据
    """
    logger.info("开始更新用户持仓...")
    try:
        db = SessionLocal()
        try:
            # 获取所有有持仓的用户
            user_ids = [
                uid for (uid,) in db.query(Holding.user_id).distinct().all()
            ]
            
            if not user_ids:
                logger.info("暂无持仓用户")
                return
            
            logger.info(f"需要更新 {len(user_ids)} 个用户持仓")
            
            for user_id in user_ids:
                try:
                    portfolio = await get_portfolio_with_valuation_async(db, user_id)
                    global_cache.update_portfolio(user_id, portfolio)
                except Exception as e:
                    logger.warning(f"用户 {user_id} 持仓更新失败: {e}")
            
            logger.info(f"[OK] 用户持仓更新完成")
            
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[ERROR] 更新用户持仓异常: {e}")


async def update_fund_rank_data():
    """
    更新基金涨跌榜缓存（含 SQLite 持久化）
    由调度器后台定时触发，避免依赖页面访问触发更新。
    """
    try:
        result = await get_fund_rank(force_refresh=True)
        top_n = len(result.get("top") or [])
        bottom_n = len(result.get("bottom") or [])
        if top_n or bottom_n:
            logger.info(f"[OK] 基金涨跌榜更新完成: top={top_n}, bottom={bottom_n}")
        else:
            logger.info("[SKIP] 基金涨跌榜本次未获取到新数据，保留旧缓存")
    except Exception as e:
        logger.warning(f"基金涨跌榜更新失败: {e}")


async def update_all_data():
    """
    完整数据更新任务
    二次判断 is_market_open()，节假日即使 CronTrigger 触发也会跳过
    """
    # ── 休市判断 ──
    if not is_market_open():
        status = get_trading_status()
        logger.info(f"[SKIP] 非交易时段({status['status_text']})，跳过数据更新")
        return

    start_time = datetime.now()
    logger.info("=" * 50)
    logger.info(f"[INFO] 开始全量数据更新 @ {start_time.strftime('%H:%M:%S')}")
    logger.info("=" * 50)
    
    try:
        # 1. 更新行情数据（最快）
        await update_market_data()
        
        # 2. 更新基金估值
        await update_fund_valuations()
        
        # 3. 更新基金涨跌榜（不依赖页面触发）
        await update_fund_rank_data()

        # 4. 更新用户持仓
        await update_user_portfolios()
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"[OK] 全量更新完成，耗时 {elapsed:.1f} 秒")
        
    except Exception as e:
        logger.error(f"[ERROR] 全量更新异常: {e}")
    finally:
        # 无论成功失败都更新时间戳
        global_cache._update_timestamp()


async def post_close_cache_refresh():
    """
    收盘后 15:05 执行：
    1. 抓取收盘行情数据（指数 / 涨跌分布 / 板块）写入缓存 + SQLite
    2. 更新基金估值 & 用户持仓缓存（保证页面可用）
    3. 保存当日最后实时估值折算为临时净值
    """
    logger.info("=" * 50)
    logger.info("[POST-CLOSE] 收盘后缓存刷新开始")
    logger.info("=" * 50)

    try:
        # 1. 行情数据 — 无论是否开盘都爬取
        await _update_market_data_impl()

        # 2. 基金估值 + 用户持仓
        await update_fund_valuations()
        await update_fund_rank_data()
        await update_user_portfolios()

        # 3. 保存临时净值
        await save_today_estimate_navs()

        logger.info("[POST-CLOSE] 收盘后缓存刷新完成")
    except Exception as e:
        logger.error(f"[POST-CLOSE] 收盘后刷新异常: {e}")


async def refresh_official_nav_and_cache_sync() -> int:
    """
    夜间官方净值刷新任务：
      1) 拉取并写入官方净值（覆盖临时估值）
      2) 若有更新，立即重算基金估值与用户持仓缓存
      3) 更新全局时间戳，前端状态栏可见“已更新”
    """
    updated = await update_official_navs()
    if updated > 0:
        logger.info(f"[OFFICIAL_SYNC] 官方净值更新 {updated} 只，开始同步估值缓存")
        await update_fund_valuations()
        await update_user_portfolios()
        global_cache._update_timestamp()
    else:
        logger.info("[OFFICIAL_SYNC] 本轮无官方净值发布，保持现有缓存")
    return updated


def init_scheduler() -> AsyncIOScheduler:
    """
    初始化并返回调度器
    """
    global scheduler
    
    if scheduler is not None:
        return scheduler
    
    scheduler = AsyncIOScheduler(
        timezone="Asia/Shanghai",
        job_defaults={
            "coalesce": True,       # 错过的任务合并执行
            "max_instances": 1,     # 同一任务最多 1 个实例
            "misfire_grace_time": 60,  # 允许延迟 60 秒
        }
    )
    
    # 添加定时任务：每 3 分钟执行一次，仅在交易时间 (09:00-15:30)
    scheduler.add_job(
        update_all_data,
        CronTrigger(
            minute="*/3",           # 每 3 分钟
            hour="9-15",            # 9点到15点
            day_of_week="mon-fri",  # 周一到周五
        ),
        id="update_all_data",
        name="全量数据更新",
        replace_existing=True,
    )
    
    # 添加行情单独更新任务：每分钟（行情变化频繁）
    scheduler.add_job(
        update_market_data,
        CronTrigger(
            minute="*",             # 每分钟
            hour="9-15",            # 9点到15点
            day_of_week="mon-fri",  # 周一到周五
        ),
        id="update_market_only",
        name="行情数据更新",
        replace_existing=True,
    )

    # ── 收盘后 15:05：刷新行情缓存 + 基金估值 + 保存临时净值（周一至周五）
    scheduler.add_job(
        post_close_cache_refresh,
        CronTrigger(
            hour="15",
            minute="5",
            day_of_week="mon-fri",
        ),
        id="post_close_refresh",
        name="收盘后缓存刷新+保存临时净值",
        replace_existing=True,
    )

    # ── 19:00 第一次尝试拉取官方净值（周一至周五）
    scheduler.add_job(
        refresh_official_nav_and_cache_sync,
        CronTrigger(
            hour="19",
            minute="0",
            day_of_week="mon-fri",
        ),
        id="official_nav_1st",
        name="官方净值更新（第1次尝试）",
        replace_existing=True,
    )

    # ── 20:30 第二次尝试（若 19:00 时官方未发布）
    scheduler.add_job(
        refresh_official_nav_and_cache_sync,
        CronTrigger(
            hour="20",
            minute="30",
            day_of_week="mon-fri",
        ),
        id="official_nav_2nd",
        name="官方净值更新（第2次尝试）",
        replace_existing=True,
    )

    # ── 22:00 最终尝试 + 全量数据补全（周一至周五）
    async def _final_nav_update():
        """22:00 最终官方净值拉取 + 缺失数据全量补全"""
        updated = await refresh_official_nav_and_cache_sync()
        logger.info(f"[FINAL_NAV] 22:00 最终尝试：{updated} 只基金官方净值已更新")
        await batch_fill_all_gaps()
        logger.info("[FINAL_NAV] 全量数据补全完成")

    scheduler.add_job(
        _final_nav_update,
        CronTrigger(
            hour="22",
            minute="0",
            day_of_week="mon-fri",
        ),
        id="official_nav_final",
        name="官方净值最终尝试 + 数据补全",
        replace_existing=True,
    )

    # ── 15:05-21:55 每 5 分钟轮询一次官方净值（停盘后持续检查基金是否发布当日净值）
    # 注：22:00 由 official_nav_final 负责最终尝试；15:05 由 save_estimate_navs 单独处理
    scheduler.add_job(
        refresh_official_nav_and_cache_sync,
        CronTrigger(
            hour="15-21",
            minute="*/5",
            day_of_week="mon-fri",
        ),
        id="official_nav_polling",
        name="停盘后每5分钟轮询官方净值",
        replace_existing=True,
    )

    # ── 每周六 10:00 处理周五可能遗漏的净值（部分基金发布较晚）
    scheduler.add_job(
        batch_fill_all_gaps,
        CronTrigger(
            hour="10",
            minute="0",
            day_of_week="sat",
        ),
        id="weekend_gap_fill",
        name="周末补全上周净值",
        replace_existing=True,
    )
    
    logger.info("[OK] 调度器初始化完成")
    return scheduler


async def start_scheduler():
    """
    启动调度器
    1. 先从 SQLite 恢复历史数据（保证页面立即可用）
    2. 仅在交易时段才执行首次爬取
    """
    global scheduler
    
    try:
        scheduler = init_scheduler()
        scheduler.start()
        global_cache.scheduler_running = True
        logger.info("[OK] 调度器已启动")
        
        # ── 1. 从 SQLite 恢复上次数据（毫秒级，不阻塞） ──
        logger.info("从 SQLite 恢复历史数据...")
        global_cache.load_from_db()
        
        # ── 2. 首次数据爬取放入后台任务，不阻塞服务器启动 ──
        async def _deferred_first_fetch():
            """延迟 2 秒后在后台执行首次数据爬取，服务器可立即响应请求"""
            await asyncio.sleep(2)
            _has_valid_market = (
                global_cache.market_indices
                and any(x.get("price") for x in global_cache.market_indices)
            )
            _has_valid_funds = bool(global_cache.fund_valuations)

            if is_market_open():
                logger.info("[STARTUP-BG] 交易时段，后台执行首次数据爬取...")
                await update_all_data()
            else:
                status = get_trading_status()
                if not _has_valid_market or not _has_valid_funds:
                    logger.info(
                        f"[STARTUP-BG] 非交易时段({status['status_text']})，"
                        f"缓存不完整(市场={'✓' if _has_valid_market else '✗'} "
                        f"基金={'✓' if _has_valid_funds else '✗'})，后台爬取收盘数据..."
                    )
                    if not _has_valid_market:
                        await _update_market_data_impl()
                    await update_fund_valuations()
                    await update_fund_rank_data()
                    await update_user_portfolios()
                else:
                    logger.info(
                        f"[STARTUP-BG] 非交易时段({status['status_text']})，"
                        f"使用 SQLite 恢复的历史数据"
                    )

            # 首次爬取完成后再补全历史净值
            await asyncio.sleep(8)
            logger.info("[STARTUP-BG] 开始后台检查/补全历史净值...")
            await batch_fill_all_gaps()
            logger.info("[STARTUP-BG] 历史净值检查完成")

        asyncio.ensure_future(_deferred_first_fetch())
        logger.info("[OK] 服务器已就绪，首次数据爬取将在后台进行")
        
    except Exception as e:
        logger.error(f"[ERROR] 调度器启动失败: {e}")
        global_cache.scheduler_running = False


def stop_scheduler():
    """
    停止调度器
    """
    global scheduler
    
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        global_cache.scheduler_running = False
        logger.info("[OK] 调度器已停止")


def get_scheduler_status() -> dict:
    """
    获取调度器状态
    """
    if scheduler is None:
        return {"running": False, "jobs": []}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })
    
    return {
        "running": scheduler.running,
        "jobs": jobs,
    }
