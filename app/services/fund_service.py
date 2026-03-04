from __future__ import annotations

"""
fund_service.py  基金数据服务

缓存策略：
  • 历史净值：DB 持久化 (FundNavHistory)
      - 首次请求：akshare 全量拉取  存入 DB  返回
      - 后续请求：DB 直接返回（毫秒级） 若数据陈旧则后台静默增量更新
      - 缺失/零值数据：调度器自动发现并在后台补全
  • 重仓持仓：DB 持久化 (FundPortfolioCache)
      - 缓存有效期 7 天（季报至多一次更新）
      - 超期时后台静默刷新，旧数据仍立即返回
  • 基金名称：in-memory TTLCache (1h)

"""

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date as date_type
from typing import Any

import akshare as ak
import pandas as pd
from cachetools import TTLCache

from app.database import SessionLocal

logger = logging.getLogger("navpulse.fund_service")

# 线程池（akshare 为同步调用，需在 executor 中执行）
_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="fund_svc")

# 正在进行后台更新的基金集合（防止重复触发）
_bg_updating: set = set()
_bg_portfolio_updating: set = set()
_linked_etf_infer_cache: TTLCache = TTLCache(maxsize=2000, ttl=86400)

# 基金名称内存缓存（TTL 1h）
_name_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)


# 
#  基金名称
# 

def get_fund_name(fund_code: str) -> str:
    """获取基金名称（带 1h 内存缓存）"""
    if fund_code in _name_cache:
        return _name_cache[fund_code]
    try:
        fund_list = ak.fund_name_em()
        if fund_list is not None and not fund_list.empty:
            matched = fund_list[fund_list["基金代码"] == fund_code]
            if not matched.empty:
                name = str(matched.iloc[0]["基金简称"])
                _name_cache[fund_code] = name
                return name
    except Exception as e:
        logger.warning(f"获取基金名称失败 ({fund_code}): {e}")
    _name_cache[fund_code] = fund_code
    return fund_code


# 
#  内部辅助
# 

def _parse_weight(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace("%", "")
    if text in {"", "nan", "None"}:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _parse_data_date(quarter_text: Any):
    if quarter_text is None:
        return None
    text = str(quarter_text).strip()
    if not text:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4})\s*年\s*([1-4])\s*季", text)
    if m:
        year, quarter = int(m.group(1)), int(m.group(2))
        return f"{year}-{['03-31','06-30','09-30','12-31'][quarter-1]}"
    return None


def _is_etf_code(code: str, name: str = "") -> bool:
    if not code:
        return False
    code = str(code).strip()
    if len(code) == 6 and code[:2] in ['51', '15', '56', '58']:
        return True
    if name and 'ETF' in name.upper():
        return True
    return False


def _is_etf_trading_code(code: str) -> bool:
    """场内 ETF 代码格式判断（用于联接基金底层 ETF 候选）"""
    c = str(code).strip()
    return len(c) == 6 and c[:2] in {"51", "15", "56", "58", "52", "16"}


def _normalize_linked_name(name: str) -> str:
    """标准化联接基金名称，便于匹配底层 ETF 名称"""
    if not name:
        return ""
    s = str(name).upper().replace(" ", "")
    s = re.sub(r"（[^）]*）|\([^\)]*\)", "", s)
    s = re.sub(r"发起式|发起", "", s)
    s = re.sub(r"联接[A-Z]?$|联接[ABCHIR]类?$", "", s)
    s = re.sub(r"[ABCHIR]类$", "", s)
    s = s.replace("基金", "")
    return s


def _extract_etf_core(name: str) -> str:
    """提取 ETF 核心名称（去管理人前缀、保留指数主题）"""
    n = _normalize_linked_name(name)
    if not n:
        return ""
    idx = n.find("ETF")
    if idx != -1:
        n = n[:idx + 3]

    keyword_hits = [
        n.find(k) for k in (
            "中证", "国证", "沪深", "上证", "深证", "创业板", "科创", "恒生", "纳指", "标普", "卫星", "通信", "半导体",
        ) if n.find(k) != -1
    ]
    if keyword_hits:
        n = n[min(keyword_hits):]
    return n


def _calc_return_corr(series_a: list[float], series_b: list[float]) -> float:
    """计算两组收益序列皮尔逊相关系数（无 numpy 依赖）"""
    if len(series_a) < 15 or len(series_b) < 15 or len(series_a) != len(series_b):
        return -1.0
    n = len(series_a)
    ma = sum(series_a) / n
    mb = sum(series_b) / n
    cov = sum((a - ma) * (b - mb) for a, b in zip(series_a, series_b))
    va = sum((a - ma) ** 2 for a in series_a)
    vb = sum((b - mb) ** 2 for b in series_b)
    if va <= 1e-12 or vb <= 1e-12:
        return -1.0
    return cov / ((va ** 0.5) * (vb ** 0.5))


def _infer_linked_etf_code(fund_code: str) -> str | None:
    """
    为 ETF 联接基金推断底层 ETF 代码：
      1) 名称相似度候选
      2) 历史净值收益相关性校验
    """
    cached = _linked_etf_infer_cache.get(fund_code)
    if cached is not None:
        return cached

    fund_name = get_fund_name(fund_code)
    if not fund_name:
        _linked_etf_infer_cache[fund_code] = None
        return None

    # 仅对联接基金启用推断，避免误伤普通 ETF/指数基金
    if "联接" not in str(fund_name):
        _linked_etf_infer_cache[fund_code] = None
        return None

    normalized_name = _normalize_linked_name(fund_name)
    core = _extract_etf_core(fund_name)
    try:
        fund_list = ak.fund_name_em()
    except Exception as e:
        logger.warning(f"[穿透推断] 读取基金列表失败 ({fund_code}): {e}")
        _linked_etf_infer_cache[fund_code] = None
        return None

    if fund_list is None or fund_list.empty:
        _linked_etf_infer_cache[fund_code] = None
        return None

    # 仅保留场内 ETF 候选
    candidates = []
    for _, row in fund_list.iterrows():
        code = str(row.get("基金代码", "")).strip()
        name = str(row.get("基金简称", "")).strip()
        if not code or code == fund_code:
            continue
        if not _is_etf_trading_code(code):
            continue
        n = _normalize_linked_name(name)
        if "ETF" not in n:
            continue
        score_name = SequenceMatcher(None, normalized_name, n).ratio()
        score_core = SequenceMatcher(None, core, _extract_etf_core(name)).ratio() if core else 0.0
        score = max(score_name * 0.7 + score_core * 0.3, score_core)
        if score < 0.45:
            continue
        candidates.append((code, name, score))

    if not candidates:
        _linked_etf_infer_cache[fund_code] = None
        return None

    candidates.sort(key=lambda x: x[2], reverse=True)
    top = candidates[:8]

    # 若名称非常确定，直接采用
    if top and top[0][2] >= 0.88:
        best = top[0][0]
        logger.info(f"[穿透推断] {fund_code} 名称高置信匹配 ETF {best} ({top[0][1]})")
        _linked_etf_infer_cache[fund_code] = best
        return best

    # 相关性校验
    base_hist = _sync_get_fund_history(fund_code, 180)
    base_map = {h.get("date"): h.get("change_pct") for h in base_hist if h.get("date") and h.get("change_pct") is not None}
    if len(base_map) < 20:
        best = top[0][0]
        _linked_etf_infer_cache[fund_code] = best
        return best

    best_code = None
    best_corr = -1.0
    for code, name, _ in top:
        etf_hist = _sync_get_fund_history(code, 180)
        etf_map = {h.get("date"): h.get("change_pct") for h in etf_hist if h.get("date") and h.get("change_pct") is not None}
        common_dates = sorted(set(base_map.keys()) & set(etf_map.keys()))
        if len(common_dates) < 20:
            continue
        a = [float(base_map[d]) for d in common_dates]
        b = [float(etf_map[d]) for d in common_dates]
        corr = _calc_return_corr(a, b)
        if corr > best_corr:
            best_corr = corr
            best_code = code

    if best_code and best_corr >= 0.75:
        logger.info(f"[穿透推断] {fund_code} 相关性匹配 ETF {best_code} (corr={best_corr:.3f})")
        _linked_etf_infer_cache[fund_code] = best_code
        return best_code

    # 兜底：取名称最相近候选
    fallback = top[0][0]
    logger.info(f"[穿透推断] {fund_code} 使用名称兜底 ETF {fallback}")
    _linked_etf_infer_cache[fund_code] = fallback
    return fallback


def _last_trading_day_str() -> str:
    """返回上一个已完成交易日的日期（简单判断：跳过周末 + 15:00 前用前一天）"""
    today = date_type.today()
    d = today
    if d.weekday() >= 5:
        d -= timedelta(days=d.weekday() - 4)
    now = datetime.now()
    if d == today and now.hour < 15:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 
#  历史净值 DB 读写
# 

def _db_get_history(fund_code: str, days: int) -> list:
    """从 DB 读取最近 days 条（升序）"""
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        rows = (
            db.query(FundNavHistory)
            .filter(FundNavHistory.fund_code == fund_code, FundNavHistory.nav > 0)
            .order_by(FundNavHistory.date.desc())
            .limit(days)
            .all()
        )
        return [{"date": r.date, "nav": r.nav, "change_pct": round(r.change_pct or 0, 4)}
                for r in reversed(rows)]
    except Exception as e:
        logger.error(f"DB 读取历史净值失败 ({fund_code}): {e}")
        return []
    finally:
        db.close()


def _db_get_all_dates(fund_code: str) -> set:
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        rows = db.query(FundNavHistory.date).filter(FundNavHistory.fund_code == fund_code).all()
        return {r.date for r in rows}
    except Exception:
        return set()
    finally:
        db.close()


def _db_get_latest_date(fund_code: str):
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        row = (
            db.query(FundNavHistory.date)
            .filter(FundNavHistory.fund_code == fund_code, FundNavHistory.nav > 0)
            .order_by(FundNavHistory.date.desc())
            .first()
        )
        return row.date if row else None
    except Exception:
        return None
    finally:
        db.close()


def _db_get_history_latest_nav(fund_code: str) -> float:
    """从 DB 获取最新净值（单次查询，极快）"""
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        row = (
            db.query(FundNavHistory.nav)
            .filter(FundNavHistory.fund_code == fund_code, FundNavHistory.nav > 0)
            .order_by(FundNavHistory.date.desc())
            .first()
        )
        return row.nav if row else 0
    except Exception:
        return 0
    finally:
        db.close()


def _db_count_history(fund_code: str) -> int:
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        return db.query(FundNavHistory).filter(
            FundNavHistory.fund_code == fund_code, FundNavHistory.nav > 0
        ).count()
    except Exception:
        return 0
    finally:
        db.close()


def _db_save_history(fund_code: str, history: list, is_estimate: int = 0):
    """
    批量 upsert 历史净值

    is_estimate=0（默认）：官方净值
      - 跳过 nav<=0 的行
      - 若已存在行 nav>0 且 is_estimate=0：不覆盖（保留历史官方数据）
      - 若已存在行 is_estimate=1（临时估算）：**强制覆盖**（官方数据优先）
    is_estimate=1：临时估算净值（仅在不存在任何 nav>0 行时写入）
    """
    if not history:
        return
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        existing_dates = _db_get_all_dates(fund_code)
        new_rows = []
        updated_count = 0
        for item in history:
            d = item["date"]
            nav = item.get("nav", 0)
            if not d or nav is None or nav <= 0:
                continue
            if d in existing_dates:
                row = db.query(FundNavHistory).filter(
                    FundNavHistory.fund_code == fund_code,
                    FundNavHistory.date == d,
                ).first()
                if row:
                    should_update = (
                        # 旧行 nav 无效 → 任何新数据都覆盖
                        (row.nav is None or row.nav <= 0)
                        # 旧行是临时估算，而新数据是官方净值 → 强制覆盖
                        or (row.is_estimate == 1 and is_estimate == 0)
                    )
                    if should_update:
                        row.nav = nav
                        row.change_pct = item.get("change_pct", 0)
                        row.is_filled = 1
                        row.is_estimate = is_estimate
                        updated_count += 1
            else:
                new_rows.append(FundNavHistory(
                    fund_code=fund_code, date=d,
                    nav=nav, change_pct=item.get("change_pct", 0),
                    is_filled=1, is_estimate=is_estimate,
                ))
        if new_rows:
            db.bulk_save_objects(new_rows)
        db.commit()
        if new_rows or updated_count:
            logger.info(
                f"[DB] ({fund_code}) 新增 {len(new_rows)} 条"
                f"{' 覆盖' + str(updated_count) + ' 条临时估算' if updated_count else ''}"
            )
    except Exception:
        db.rollback()
        # 降级为逐条 upsert
        try:
            db2 = SessionLocal()
            for item in history:
                nav = item.get("nav", 0)
                if not item.get("date") or nav is None or nav <= 0:
                    continue
                row = db2.query(FundNavHistory).filter(
                    FundNavHistory.fund_code == fund_code,
                    FundNavHistory.date == item["date"],
                ).first()
                if row:
                    should_update = (
                        (row.nav is None or row.nav <= 0)
                        or (row.is_estimate == 1 and is_estimate == 0)
                    )
                    if should_update:
                        row.nav = nav
                        row.change_pct = item.get("change_pct", 0)
                        row.is_estimate = is_estimate
                else:
                    db2.add(FundNavHistory(
                        fund_code=fund_code, date=item["date"],
                        nav=nav, change_pct=item.get("change_pct", 0),
                        is_filled=1, is_estimate=is_estimate,
                    ))
            db2.commit()
        except Exception as e2:
            logger.error(f"DB 逐条写入失败 ({fund_code}): {e2}")
        finally:
            db2.close()
    finally:
        db.close()


# 
#  akshare 历史净值拉取（同步）
# 

def _parse_akshare_df(df: "pd.DataFrame") -> list:
    result = []
    prev_nav = None
    for _, row in df.iterrows():
        date_val = row.get("净值日期", row.get("日期", ""))
        nav_val = row.get("单位净值", row.get("净值", 0))
        date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10]
        nav = float(nav_val) if nav_val else 0
        if nav <= 0:
            continue
        change_pct = round((nav - prev_nav) / prev_nav * 100, 4) if prev_nav and prev_nav > 0 else 0.0
        result.append({"date": date_str, "nav": round(nav, 4), "change_pct": change_pct})
        prev_nav = nav
    return result


def _sync_fetch_all_history(fund_code: str) -> list:
    """从 akshare 全量拉取历史净值（同步，用于首次初始化或后台增量更新）"""
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df is None or df.empty:
            return []
        return _parse_akshare_df(df)
    except Exception as e:
        logger.warning(f"akshare 拉取历史失败 ({fund_code}): {e}")
        return []


# 
#  后台静默更新（不阻塞 API 响应）
# 

async def _bg_update_history(fund_code: str):
    """后台增量更新基金历史净值：全量拉 akshare，仅 upsert 新行"""
    if fund_code in _bg_updating:
        return
    _bg_updating.add(fund_code)
    try:
        loop = asyncio.get_event_loop()
        fresh = await loop.run_in_executor(_executor, _sync_fetch_all_history, fund_code)
        if fresh:
            await loop.run_in_executor(_executor, _db_save_history, fund_code, fresh)
            logger.info(f"[BG] 历史净值更新完成 ({fund_code}, {len(fresh)} 条)")
        else:
            logger.warning(f"[BG] akshare 返回空数据 ({fund_code})")
    except Exception as e:
        logger.error(f"[BG] 历史净值更新异常 ({fund_code}): {e}")
    finally:
        _bg_updating.discard(fund_code)


async def fill_nav_gaps_for_fund(fund_code: str):
    """发现并修复该基金历史净值中的零值/缺失行"""
    if fund_code in _bg_updating:
        return
    count = _db_count_history(fund_code)
    if count < 30:
        await _bg_update_history(fund_code)
        return
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        zero_count = db.query(FundNavHistory).filter(
            FundNavHistory.fund_code == fund_code, FundNavHistory.nav <= 0
        ).count()
    except Exception:
        zero_count = 0
    finally:
        db.close()
    if zero_count:
        logger.info(f"[GAP] {fund_code} 发现 {zero_count} 条零值，触发补全")
        await _bg_update_history(fund_code)


# 
#  对外接口：基金历史净值
# 

async def get_fund_history_async(fund_code: str, days: int = 90) -> dict:
    """
    获取基金历史净值  DB 优先 + 后台静默增量更新

    流程：
      1. DB 数据充足   立即返回旧数据，若陈旧则触发后台更新
      2. DB 数据不足   首次全量拉取（用户等一次），存 DB 后返回
    """
    loop = asyncio.get_event_loop()

    db_data = await loop.run_in_executor(_executor, _db_get_history, fund_code, days)
    latest_date = db_data[-1]["date"] if db_data else None
    sufficient = len(db_data) >= max(int(days * 0.6), 5)

    if sufficient:
        last_trading = _last_trading_day_str()
        if (latest_date is None or latest_date < last_trading) and fund_code not in _bg_updating:
            asyncio.create_task(_bg_update_history(fund_code))
        name = await loop.run_in_executor(_executor, get_fund_name, fund_code)
        return _build_history_resp(fund_code, name, db_data, latest_date)

    # 首次全量拉取
    logger.info(f"[FIRST] 全量拉取历史净值 ({fund_code})")
    all_history = await loop.run_in_executor(_executor, _sync_fetch_all_history, fund_code)
    if all_history:
        asyncio.create_task(asyncio.to_thread(_db_save_history, fund_code, all_history))
        trimmed = all_history[-days:] if len(all_history) > days else all_history
    else:
        trimmed = db_data  # fallback 到可能不足的 DB 数据

    name = await loop.run_in_executor(_executor, get_fund_name, fund_code)
    data_date = trimmed[-1]["date"] if trimmed else None
    return _build_history_resp(fund_code, name, trimmed, data_date)


def _build_history_resp(fund_code: str, name: str, history: list, data_date) -> dict:
    result = {
        "fund_code": fund_code,
        "fund_name": name,
        "history": history,
        "count": len(history),
        "updated_at": data_date or "",
    }
    if history:
        max_nav = max(history, key=lambda x: x["nav"])
        min_nav = min(history, key=lambda x: x["nav"])
        result["max_point"] = {"date": max_nav["date"], "nav": max_nav["nav"]}
        result["min_point"] = {"date": min_nav["date"], "nav": min_nav["nav"]}
    return result


# 
#  重仓持仓 DB 缓存
# 

PORTFOLIO_CACHE_TTL_DAYS = 7


def _db_get_portfolio(fund_code: str):
    from app.models import FundPortfolioCache
    db = SessionLocal()
    try:
        row = db.query(FundPortfolioCache).filter(
            FundPortfolioCache.fund_code == fund_code
        ).first()
        if row is None:
            return None
        holdings = json.loads(row.holdings_json or "[]")
        result = {
            "fund_code": fund_code,
            "data_date": row.data_date,
            "updated_at": row.updated_at,
            "holdings": holdings,
            "total_weight": sum(h.get("weight", 0) for h in holdings),
        }
        # 联接基金穿透的底层 ETF 代码
        pf = getattr(row, "penetrated_from", None)
        if pf:
            result["penetrated_from"] = pf
        return result
    except Exception as e:
        logger.error(f"DB 读取持仓缓存失败 ({fund_code}): {e}")
        return None
    finally:
        db.close()


def _db_save_portfolio(fund_code: str, portfolio: dict):
    from app.models import FundPortfolioCache
    db = SessionLocal()
    try:
        holdings = portfolio.get("holdings", [])
        now = _now_str()
        penetrated = portfolio.get("penetrated_from")
        row = db.query(FundPortfolioCache).filter(
            FundPortfolioCache.fund_code == fund_code
        ).first()
        if row:
            row.holdings_json = json.dumps(holdings, ensure_ascii=False)
            row.data_date = portfolio.get("data_date")
            row.updated_at = now
            if penetrated is not None:
                row.penetrated_from = penetrated
        else:
            db.add(FundPortfolioCache(
                fund_code=fund_code,
                holdings_json=json.dumps(holdings, ensure_ascii=False),
                data_date=portfolio.get("data_date"),
                updated_at=now,
                penetrated_from=penetrated,
            ))
        db.commit()
        logger.info(f"[DB] 持仓缓存已更新 ({fund_code}, {len(holdings)} 只" + (f", ETF={penetrated}" if penetrated else "") + ")")
    except Exception as e:
        db.rollback()
        logger.error(f"DB 写入持仓缓存失败 ({fund_code}): {e}")
    finally:
        db.close()


def _is_portfolio_stale(updated_at: str) -> bool:
    if not updated_at:
        return True
    try:
        t = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - t).days >= PORTFOLIO_CACHE_TTL_DAYS
    except ValueError:
        return True


def _sync_fetch_portfolio(fund_code: str, _depth: int = 0) -> dict:
    """同步从 akshare 拉取持仓（含联接基金穿透）"""
    MAX_DEPTH = 3
    if _depth >= MAX_DEPTH:
        return {"fund_code": fund_code, "data_date": None, "holdings": []}

    current_year = datetime.now().year
    df = pd.DataFrame()
    for year in [current_year, current_year - 1]:
        try:
            temp = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(year))
            if temp is not None and not temp.empty:
                df = temp
                break
        except Exception:
            continue

    if df.empty:
        inferred_etf = _infer_linked_etf_code(fund_code) if _depth < MAX_DEPTH else None
        if inferred_etf:
            logger.info(f"[穿透推断] {fund_code} 未取到持仓，尝试穿透 ETF {inferred_etf}")
            etf = _sync_fetch_portfolio(inferred_etf, _depth=_depth + 1)
            if etf.get("holdings"):
                return {
                    "fund_code": fund_code,
                    "data_date": etf.get("data_date"),
                    "total_weight": etf.get("total_weight", 0),
                    "holdings": etf.get("holdings"),
                    "penetrated_from": inferred_etf,
                }
            return {
                "fund_code": fund_code,
                "data_date": None,
                "holdings": [],
                "total_weight": 0,
                "penetrated_from": inferred_etf,
            }
        return {"fund_code": fund_code, "data_date": None, "holdings": []}

    latest_quarter = df["季度"].max()
    latest_df = df[df["季度"] == latest_quarter].copy()
    data_date = _parse_data_date(latest_quarter)

    holdings, total_weight = [], 0.0
    for _, row in latest_df.iterrows():
        weight = _parse_weight(row.get("占净值比例"))
        holdings.append({
            "code": str(row.get("股票代码", "")).strip(),
            "name": str(row.get("股票名称", "")).strip(),
            "weight": weight,
        })
        total_weight += weight

    # 联接基金穿透
    if holdings and _depth < MAX_DEPTH:
        s = sorted(holdings, key=lambda x: x.get("weight", 0), reverse=True)
        top = s[0]
        if _is_etf_code(top.get("code", ""), top.get("name", "")) and top.get("weight", 0) > 60:
            logger.info(f"[穿透] {fund_code}  ETF {top['code']} ({top['name']})")
            etf = _sync_fetch_portfolio(top["code"], _depth=_depth + 1)
            if etf.get("holdings"):
                return {
                    "fund_code": fund_code,
                    "data_date": etf.get("data_date") or data_date,
                    "total_weight": etf.get("total_weight", 0),
                    "holdings": etf.get("holdings"),
                    "penetrated_from": top["code"],
                }

    inferred_etf = _infer_linked_etf_code(fund_code) if _depth < MAX_DEPTH else None
    if inferred_etf and inferred_etf != fund_code:
        etf = _sync_fetch_portfolio(inferred_etf, _depth=_depth + 1)
        if etf.get("holdings"):
            return {
                "fund_code": fund_code,
                "data_date": etf.get("data_date") or data_date,
                "total_weight": etf.get("total_weight", 0),
                "holdings": etf.get("holdings"),
                "penetrated_from": inferred_etf,
            }

    base_result = {
        "fund_code": fund_code,
        "data_date": data_date,
        "total_weight": round(total_weight, 2),
        "holdings": holdings,
    }
    if inferred_etf:
        base_result["penetrated_from"] = inferred_etf
    return base_result


def get_fund_portfolio(fund_code: str, _depth: int = 0) -> dict:
    """
    获取基金重仓持仓（同步版，供 valuation_service 在 executor 中调用）
    策略：DB 缓存优先（7天有效期），失效则拉取 akshare 并更新 DB
    """
    cached = _db_get_portfolio(fund_code)
    invalid_penetration = (
        cached is not None
        and cached.get("penetrated_from")
        and not _is_etf_trading_code(cached.get("penetrated_from"))
    )
    if invalid_penetration:
        logger.warning(f"持仓缓存中的穿透 ETF 无效，触发刷新 ({fund_code} -> {cached.get('penetrated_from')})")

    if cached and not invalid_penetration and not _is_portfolio_stale(cached.get("updated_at", "")):
        return cached

    fresh = _sync_fetch_portfolio(fund_code, _depth=_depth)
    if fresh.get("holdings") or fresh.get("penetrated_from"):
        _db_save_portfolio(fund_code, fresh)
    elif cached:
        logger.warning(f"持仓拉取失败，使用旧缓存 ({fund_code})")
        return cached

    return fresh


async def _bg_refresh_portfolio(fund_code: str):
    """后台静默刷新持仓缓存"""
    if fund_code in _bg_portfolio_updating:
        return
    _bg_portfolio_updating.add(fund_code)
    try:
        loop = asyncio.get_event_loop()
        fresh = await loop.run_in_executor(_executor, _sync_fetch_portfolio, fund_code)
        if fresh.get("holdings"):
            await loop.run_in_executor(_executor, _db_save_portfolio, fund_code, fresh)
            logger.info(f"[BG] 持仓缓存已刷新 ({fund_code})")
    except Exception as e:
        logger.error(f"[BG] 持仓刷新异常 ({fund_code}): {e}")
    finally:
        _bg_portfolio_updating.discard(fund_code)


async def get_fund_portfolio_async(fund_code: str) -> dict:
    """
    异步获取基金持仓（DB 优先 + 后台静默刷新过期缓存）
    """
    loop = asyncio.get_event_loop()
    cached = await loop.run_in_executor(_executor, _db_get_portfolio, fund_code)
    if cached:
        invalid_penetration = (
            cached.get("penetrated_from")
            and not _is_etf_trading_code(cached.get("penetrated_from"))
        )
        if invalid_penetration:
            asyncio.create_task(_bg_refresh_portfolio(fund_code))
        elif _is_portfolio_stale(cached.get("updated_at", "")):
            asyncio.create_task(_bg_refresh_portfolio(fund_code))
        return cached
    # 首次拉取
    logger.info(f"[FIRST] 首次拉取持仓 ({fund_code})")
    result = await loop.run_in_executor(_executor, _sync_fetch_portfolio, fund_code)
    if result.get("holdings") or result.get("penetrated_from"):
        asyncio.create_task(asyncio.to_thread(_db_save_portfolio, fund_code, result))
    return result


# 
#  批量操作：供调度器调用
# 

async def batch_update_all_tracked_funds():
    """每日收盘后增量更新所有被跟踪基金的历史净值"""
    from app.models import Holding, Watchlist
    db = SessionLocal()
    try:
        holding_codes = {h.code for h in db.query(Holding).distinct(Holding.code).all()}
        watchlist_codes = {w.fund_code for w in db.query(Watchlist).distinct(Watchlist.fund_code).all()}
        all_codes = holding_codes | watchlist_codes
    finally:
        db.close()

    if not all_codes:
        return
    logger.info(f"[BATCH] 批量更新历史净值 ({len(all_codes)} 只基金)")
    sem = asyncio.Semaphore(3)

    async def _one(code):
        async with sem:
            await _bg_update_history(code)

    await asyncio.gather(*[_one(c) for c in all_codes], return_exceptions=True)
    logger.info("[BATCH] 历史净值批量更新完成")


async def batch_fill_all_gaps():
    """扫描所有被跟踪基金，发现并修复缺失历史净值"""
    from app.models import Holding, Watchlist
    db = SessionLocal()
    try:
        holding_codes = {h.code for h in db.query(Holding).distinct(Holding.code).all()}
        watchlist_codes = {w.fund_code for w in db.query(Watchlist).distinct(Watchlist.fund_code).all()}
        all_codes = holding_codes | watchlist_codes
    finally:
        db.close()

    if not all_codes:
        return
    logger.info(f"[GAP_FILL] 扫描 {len(all_codes)} 只基金的数据缺失")
    for code in all_codes:
        try:
            await fill_nav_gaps_for_fund(code)
        except Exception as e:
            logger.warning(f"[GAP_FILL] {code} 补全失败: {e}")


# 
#  指定日期净值查询（用于交易记录中计算净值）
# 

def get_nav_on_date(fund_code: str, target_date: str) -> float:
    """查询基金在目标日期的净值（DB 优先，向前最多找 5 个交易日）"""
    from app.models import FundNavHistory
    db = SessionLocal()
    try:
        row = db.query(FundNavHistory).filter(
            FundNavHistory.fund_code == fund_code,
            FundNavHistory.date == target_date,
            FundNavHistory.nav > 0,
        ).first()
        if row:
            return row.nav

        target = datetime.strptime(target_date, "%Y-%m-%d")
        for i in range(1, 6):
            check_date = (target - timedelta(days=i)).strftime("%Y-%m-%d")
            row = db.query(FundNavHistory).filter(
                FundNavHistory.fund_code == fund_code,
                FundNavHistory.date == check_date,
                FundNavHistory.nav > 0,
            ).first()
            if row:
                return row.nav
    except Exception as e:
        logger.warning(f"DB 查询净值失败 ({fund_code}, {target_date}): {e}")
    finally:
        db.close()

    # DB 无数据，回退 akshare
    try:
        all_history = _sync_fetch_all_history(fund_code)
        nav_map = {h["date"]: h["nav"] for h in all_history}
        if target_date in nav_map:
            return nav_map[target_date]
        target = datetime.strptime(target_date, "%Y-%m-%d")
        for i in range(5):
            d = (target - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in nav_map:
                return nav_map[d]
    except Exception:
        pass
    return 0


async def get_nav_on_date_async(fund_code: str, target_date: str) -> float:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, get_nav_on_date, fund_code, target_date)


# 
#  收盘后临时净值 / 官方净值更新
# 

def _get_all_tracked_codes() -> set:
    """获取所有被跟踪基金代码（持仓 + 自选）"""
    from app.models import Holding, Watchlist
    db = SessionLocal()
    try:
        holding_codes = {h.code for h in db.query(Holding).distinct(Holding.code).all()}
        watchlist_codes = {w.fund_code for w in db.query(Watchlist).distinct(Watchlist.fund_code).all()}
        return holding_codes | watchlist_codes
    finally:
        db.close()


async def save_today_estimate_navs(fund_codes: set | None = None):
    """
    收盘后（15:05）将当日最后一次实时估值折算为临时净值并写入 FundNavHistory (is_estimate=1)

    逻辑：
      1. 若当日 FundNavHistory 已有 is_estimate=0 的官方行 → 跳过（官方已发布）
      2. 取 IntradayEstimate 最后一条 estimate_change（当日最新估值变动）
      3. 取上一个交易日的官方净值作为基准 prev_nav
      4. 计算 today_nav = prev_nav × (1 + estimate_change / 100)
      5. 以 is_estimate=1 写入（不覆盖 is_estimate=0 行）
    """
    from app.models import IntradayEstimate, FundNavHistory
    from zoneinfo import ZoneInfo

    codes = fund_codes or _get_all_tracked_codes()
    if not codes:
        return

    today_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    logger.info(f"[ESTIMATE_NAV] 保存 {today_str} 临时净值，共 {len(codes)} 只基金")
    saved = 0

    loop = asyncio.get_event_loop()

    async def _fetch_estimate_from_intraday(code: str) -> float | None:
        """当 IntradayEstimate 无当日记录时，实时爬取收盘分时数据，返回最后有效涨跌幅"""
        try:
            from app.services.valuation_service import calculate_intraday_from_stocks
            result = await calculate_intraday_from_stocks(code)
            points = result.get("points", [])
            if not points:
                return None
            # 取最后一个有效点
            for pt in reversed(points):
                val = pt.get("change")
                if val is not None:
                    return float(val)
        except Exception as e:
            logger.warning(f"[ESTIMATE_NAV] {code} 实时爬取兜底失败: {e}")
        return None

    def _process_one(code: str):
        db = SessionLocal()
        try:
            # 1. 当日是否已有官方净值？
            official_row = db.query(FundNavHistory).filter(
                FundNavHistory.fund_code == code,
                FundNavHistory.date == today_str,
                FundNavHistory.is_estimate == 0,
                FundNavHistory.nav > 0,
            ).first()
            if official_row:
                return None, None  # 已有官方净值，无需写临时（用 None 表示跳过）

            # 2. 当日最后一条非零估值变动（收盘时刻快照可能为0，取最后一个非零0的）
            last_est = db.query(IntradayEstimate).filter(
                IntradayEstimate.fund_code == code,
                IntradayEstimate.trade_date == today_str,
                IntradayEstimate.estimate_change != 0,
            ).order_by(IntradayEstimate.time.desc()).first()

            estimate_change = last_est.estimate_change if last_est is not None else None

            # 3. 上一个有效官方净值
            prev_row = db.query(FundNavHistory).filter(
                FundNavHistory.fund_code == code,
                FundNavHistory.date < today_str,
                FundNavHistory.is_estimate == 0,
                FundNavHistory.nav > 0,
            ).order_by(FundNavHistory.date.desc()).first()
            if prev_row is None:
                logger.debug(f"[ESTIMATE_NAV] {code} 无历史官方净值基准，跳过")
                return None, None   # (prev_nav, estimate_change)

            return prev_row.nav, estimate_change   # estimate_change 可能为 None
        except Exception as e:
            logger.error(f"[ESTIMATE_NAV] {code} DB 查询失败: {e}")
            return None, None
        finally:
            db.close()

    def _write_nav(code: str, prev_nav: float, estimate_change: float):
        """将临时净值写入 FundNavHistory"""
        db = SessionLocal()
        try:
            today_nav = round(prev_nav * (1 + estimate_change / 100), 4)
            if today_nav <= 0:
                return False
            existing = db.query(FundNavHistory).filter(
                FundNavHistory.fund_code == code,
                FundNavHistory.date == today_str,
            ).first()
            if existing:
                if existing.is_estimate == 1:
                    existing.nav = today_nav
                    existing.change_pct = round(estimate_change, 4)
            else:
                db.add(FundNavHistory(
                    fund_code=code,
                    date=today_str,
                    nav=today_nav,
                    change_pct=round(estimate_change, 4),
                    is_filled=1,
                    is_estimate=1,
                ))
            db.commit()
            logger.info(
                f"[ESTIMATE_NAV] {code} 写入临时净值 {today_nav:.4f}"
                f"（基准={prev_nav:.4f}, 估值变动={estimate_change:+.2f}%）"
            )
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"[ESTIMATE_NAV] {code} 写入失败: {e}")
            return False
        finally:
            db.close()

    sem = asyncio.Semaphore(4)

    async def _one(code):
        async with sem:
            prev_nav, estimate_change = await loop.run_in_executor(_executor, _process_one, code)
            if prev_nav is None:
                return False
            # IntradayEstimate 无记录 → 实时爬取兜底
            if estimate_change is None:
                logger.info(f"[ESTIMATE_NAV] {code} DB 无快照，尝试实时爬取收盘估值…")
                estimate_change = await _fetch_estimate_from_intraday(code)
                if estimate_change is None:
                    logger.warning(f"[ESTIMATE_NAV] {code} 实时爬取也失败，放弃")
                    return False
            return await loop.run_in_executor(_executor, _write_nav, code, prev_nav, estimate_change)

    results = await asyncio.gather(*[_one(c) for c in codes], return_exceptions=True)
    saved = sum(1 for r in results if r is True)
    logger.info(f"[ESTIMATE_NAV] 完成，成功写入 {saved}/{len(codes)} 只基金临时净值")


async def update_official_navs(fund_codes: set | None = None) -> int:
    """
    尝试拉取官方净值并覆盖临时估算净值（调度器在 19:00 / 20:30 / 22:00 调用）

    逻辑：
      1. 拉取每只基金最近 5 天 akshare 净值
      2. 若当日日期出现在结果中（nav>0）→ 官方净值已发布
      3. 以 is_estimate=0 调用 _db_save_history，覆盖临时估算行
      4. 返回实际更新的基金数量（0 = 官方还未发布）
    """
    from zoneinfo import ZoneInfo

    codes = fund_codes or _get_all_tracked_codes()
    if not codes:
        return 0

    today_str = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    logger.info(f"[OFFICIAL_NAV] 尝试更新 {today_str} 官方净值，共 {len(codes)} 只基金")
    updated = 0

    loop = asyncio.get_event_loop()

    def _try_update_one(code: str) -> bool:
        """拉取近 5 天数据，若当日净值存在则写入 DB"""
        try:
            # 仅拉最近 5 天（加速、减少 akshare 请求量）
            five_days_ago = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
            today_compact = datetime.now().strftime("%Y%m%d")
            try:
                df = ak.fund_open_fund_info_em(
                    symbol=code,
                    indicator="单位净值走势",
                    start_date=five_days_ago,
                    end_date=today_compact,
                )
                history = _parse_akshare_df(df) if df is not None and not df.empty else []
            except Exception:
                # 部分版本 akshare 不支持 date 参数，回退全量拉取并截取
                history = _sync_fetch_all_history(code)
                history = [h for h in history if h.get("date", "") >= (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")]

            today_items = [h for h in history if h.get("date") == today_str and h.get("nav", 0) > 0]
            if not today_items:
                return False  # 官方净值尚未发布
            _db_save_history(code, history, is_estimate=0)
            logger.info(f"[OFFICIAL_NAV] {code} 官方净值已更新 nav={today_items[0]['nav']:.4f}")
            return True
        except Exception as e:
            logger.warning(f"[OFFICIAL_NAV] {code} 拉取失败: {e}")
            return False

    sem = asyncio.Semaphore(3)

    async def _one(code):
        async with sem:
            return await loop.run_in_executor(_executor, _try_update_one, code)

    results = await asyncio.gather(*[_one(c) for c in codes], return_exceptions=True)
    updated = sum(1 for r in results if r is True)
    logger.info(f"[OFFICIAL_NAV] 完成，{updated}/{len(codes)} 只基金获得官方净值")
    return updated


# 
#  向后兼容：保留旧函数名供内部调用
# 

def _sync_get_fund_history(fund_code: str, days: int = 90) -> list:
    """兼容旧版调用，优先从 DB 读取"""
    db_data = _db_get_history(fund_code, days)
    if len(db_data) >= max(int(days * 0.6), 5):
        return db_data
    return _sync_fetch_all_history(fund_code)[-days:]
