"""
交易日历服务 — 判断当前是否为 A 股交易时间

功能:
    - is_trading_day(dt)        是否交易日（排除周末 + 法定假日）
    - is_trading_time(dt)       是否在交易时段 (09:15-15:05)
    - is_market_open()          综合判断：当前是否应该爬取数据
    - current_display_trade_date() 当前页面应展示的交易日
    - in_live_display_window()  是否处于“当天 09:30-24:00 必须展示当日数据”窗口
"""
from __future__ import annotations

from datetime import datetime, date
from zoneinfo import ZoneInfo

# A股所在时区
_TZ = ZoneInfo("Asia/Shanghai")

# ══════════════════════════════════════════════════════════
#  中国法定节假日（含调休）
#  每年底更新下一年日期即可
# ══════════════════════════════════════════════════════════

HOLIDAYS: set[date] = {
    #  ── 2025 ─────────────────────
    # 元旦
    date(2025, 1, 1),
    # 春节
    date(2025, 1, 28), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 1, 31), date(2025, 2, 1), date(2025, 2, 2),
    date(2025, 2, 3), date(2025, 2, 4),
    # 清明
    date(2025, 4, 4), date(2025, 4, 5), date(2025, 4, 6),
    # 劳动节
    date(2025, 5, 1), date(2025, 5, 2), date(2025, 5, 3),
    date(2025, 5, 4), date(2025, 5, 5),
    # 端午
    date(2025, 5, 31), date(2025, 6, 1), date(2025, 6, 2),
    # 中秋+国庆
    date(2025, 10, 1), date(2025, 10, 2), date(2025, 10, 3),
    date(2025, 10, 4), date(2025, 10, 5), date(2025, 10, 6),
    date(2025, 10, 7), date(2025, 10, 8),

    #  ── 2026 ─────────────────────
    # 元旦
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    # 春节  (2026-02-17 除夕)
    date(2026, 2, 14), date(2026, 2, 15), date(2026, 2, 16),
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
    date(2026, 2, 20),
    # 清明
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    # 劳动节
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 4), date(2026, 5, 5),
    # 端午
    date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
    # 中秋
    date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27),
    # 国庆
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6),
    date(2026, 10, 7), date(2026, 10, 8),
}


def now_shanghai() -> datetime:
    """返回当前上海时间"""
    return datetime.now(_TZ)


def previous_trading_day(dt: datetime | date | None = None) -> date:
    """返回给定日期之前最近一个交易日。"""
    if dt is None:
        dt = now_shanghai()
    current = dt.date() if isinstance(dt, datetime) else dt
    from datetime import timedelta

    current -= timedelta(days=1)
    while not is_trading_day(current):
        current -= timedelta(days=1)
    return current


def is_trading_day(dt: datetime | date | None = None) -> bool:
    """
    判断是否为交易日（非周末、非法定假日）
    """
    if dt is None:
        dt = now_shanghai()
    d = dt.date() if isinstance(dt, datetime) else dt

    # 周六日
    if d.weekday() >= 5:
        return False
    # 法定假日
    if d in HOLIDAYS:
        return False
    return True


def is_trading_time(dt: datetime | None = None) -> bool:
    """
    判断是否在交易时段内
    A 股交易时间: 09:30-11:30, 13:00-15:00
    扩展范围:     09:15-15:05  (含集合竞价 + 收盘后缓冲)
    """
    if dt is None:
        dt = now_shanghai()

    if not is_trading_day(dt):
        return False

    t = dt.time()
    from datetime import time as _time
    # 09:15 ~ 11:35
    if _time(9, 15) <= t <= _time(11, 35):
        return True
    # 12:55 ~ 15:05
    if _time(12, 55) <= t <= _time(15, 5):
        return True
    return False


def is_market_open() -> bool:
    """
    综合判断: 当前是否应该主动爬取新数据
    等同于 is_trading_time() 的别名，语义更清晰
    """
    return is_trading_time()


def in_live_display_window(dt: datetime | None = None) -> bool:
    """
    是否处于“当天 09:30-24:00 必须展示当日数据”的窗口。
    该窗口内若实时接口失败，宁可返回空/0，也不能继续展示昨日数据。
    """
    if dt is None:
        dt = now_shanghai()
    if not is_trading_day(dt):
        return False

    from datetime import time as _time
    return dt.time() >= _time(9, 30)


def current_display_trade_date(dt: datetime | None = None) -> str:
    """
    返回当前页面应该展示的交易日：
    - 交易日 09:30-24:00：展示当天
    - 其余时段：展示最近一个已完成交易日
    """
    if dt is None:
        dt = now_shanghai()

    if in_live_display_window(dt):
        return dt.strftime("%Y-%m-%d")

    if is_trading_day(dt):
        from datetime import time as _time
        if dt.time() < _time(9, 30):
            return previous_trading_day(dt).strftime("%Y-%m-%d")

    return previous_trading_day(dt).strftime("%Y-%m-%d")


def get_trading_status() -> dict:
    """
    返回当前交易状态的完整信息（供 API 使用）
    """
    dt = now_shanghai()
    trading_day = is_trading_day(dt)
    trading_time = is_trading_time(dt)

    if trading_time:
        status_text = "交易中"
    elif trading_day:
        t = dt.time()
        from datetime import time as _time
        if t < _time(9, 15):
            status_text = "盘前"
        elif t > _time(15, 5):
            status_text = "已收盘"
        else:
            status_text = "午间休市"
    else:
        # 非交易日
        if dt.date().weekday() >= 5:
            status_text = "周末休市"
        elif dt.date() in HOLIDAYS:
            status_text = "节假日休市"
        else:
            status_text = "休市"

    return {
        "is_trading_day": trading_day,
        "is_trading_time": trading_time,
        "status_text": status_text,
        "server_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
    }
