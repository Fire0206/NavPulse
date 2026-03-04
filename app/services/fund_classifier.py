"""
基金分类服务
根据基金代码 / 名称 / 东方财富基金类型，自动识别基金类别，
返回适用的估值策略（ETF场内 / ETF联接 / QDII海外 / 重仓股加权 / 仅净值）

分类优先级:
  1. QDII 类（海外投资）→ overseas_index 估值
  2. ETF 联接基金        → etf_linked   估值（底层 ETF 场内实时价格）
  3. 场内 ETF             → etf_realtime 估值（ETF 场内价格直取）
  4. 普通股票 / 混合型    → weighted_holdings（现有重仓股加权算法）
  5. 债券 / 货币型        → nav_only（仅显示历史净值，不做日内估值）

缓存: TTLCache 2h（基金类型很少变化）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from cachetools import TTLCache

logger = logging.getLogger("navpulse.classifier")

# ── 分类缓存 (2h) ──
_classify_cache: TTLCache = TTLCache(maxsize=3000, ttl=7200)


# ══════════════════════════════════════════════════════════
#  分类结果数据类
# ══════════════════════════════════════════════════════════

@dataclass
class FundClassification:
    """基金分类结果，指导估值引擎选择策略"""
    fund_type: str
    """
    基金类别:
      etf             场内 ETF
      etf_linked      ETF 联接基金
      qdii_us         QDII-美股 / 纳斯达克 / 标普
      qdii_hk         QDII-港股 / 恒生
      qdii_jp         QDII-日本
      qdii_eu         QDII-欧洲 / DAX
      qdii_global     QDII-全球混合
      stock           A 股股票型
      mixed           混合型
      bond            债券型
      money           货币型
      other           其他
    """

    estimation_method: str
    """
    估值方法:
      etf_realtime        直接取 ETF 场内实时涨跌幅
      etf_linked          通过底层 ETF 场内价格估值
      overseas_index      使用海外指数涨跌幅
      weighted_holdings   重仓股实时行情加权（现有算法）
      nav_only            不做日内估值，仅返回历史净值
    """

    benchmark_index: str | None = None
    """QDII 跟踪的海外指数标识 (nasdaq / sp500 / hangseng / ...)"""

    settlement_delay: int = 0
    """结算延迟天数: T+0=0, T+1=1, T+2=2"""

    description: str = ""
    """人类可读的类型描述，供前端展示"""

    fund_type_raw: str = ""
    """东方财富原始基金类型字段"""


# ══════════════════════════════════════════════════════════
#  QDII 指数关键词映射
# ══════════════════════════════════════════════════════════

# (正则, 指数标识, 延迟天数, 描述)
_QDII_BENCHMARK_RULES: list[tuple[str, str, int, str]] = [
    # 美股指数
    (r"纳斯达克|纳指|NASDAQ|纳100",    "nasdaq",   2, "QDII-纳斯达克"),
    (r"标普500|标普|S&P",              "sp500",    2, "QDII-标普500"),
    (r"道琼斯|道指",                    "dji",      2, "QDII-道琼斯"),
    # 港股
    (r"恒生|港股|港中小|中概互联|中国互联|港股通",  "hangseng", 1, "QDII-港股"),
    (r"H股",                           "hangseng", 1, "QDII-H股"),
    # 日本
    (r"日经|日本|东证",                 "nikkei",   1, "QDII-日本"),
    # 欧洲
    (r"DAX|德国|德指",                  "dax",      2, "QDII-欧洲"),
    (r"富时|英国|FTSE",                 "ftse",     2, "QDII-英国"),
    (r"法国|CAC",                       "cac",      2, "QDII-法国"),
    (r"欧洲|欧元",                      "dax",      2, "QDII-欧洲"),
    # 全球 / 美股兜底
    (r"全球|环球|世界|MSCI|国际",        "sp500",    2, "QDII-全球"),
    (r"美国|美股|美元",                  "sp500",    2, "QDII-美股"),
]


# ══════════════════════════════════════════════════════════
#  公开 API
# ══════════════════════════════════════════════════════════

def classify_fund(fund_code: str) -> FundClassification:
    """
    分类基金并返回估值策略

    此函数为同步调用（含 akshare 网络请求），
    在 valuation_service 中应通过 asyncio.to_thread 调用
    """
    if fund_code in _classify_cache:
        return _classify_cache[fund_code]

    result = _do_classify(fund_code)
    _classify_cache[fund_code] = result
    logger.info("[分类] %s → %s (%s)", fund_code, result.fund_type, result.description)
    return result


def get_fund_type_label(fund_code: str) -> str:
    """获取基金类型的简短中文标签，适合前端 badge 展示"""
    c = classify_fund(fund_code)
    return c.description or c.fund_type


# ══════════════════════════════════════════════════════════
#  内部实现
# ══════════════════════════════════════════════════════════

def _do_classify(fund_code: str) -> FundClassification:
    """核心分类逻辑"""
    fund_name, fund_type_raw = _get_fund_info(fund_code)

    # ── 1. QDII 类（最高优先级，即使是联接基金也优先走海外指数） ──
    is_qdii = (
        "QDII" in fund_type_raw
        or "海外" in fund_type_raw
        or "QDII" in fund_name
    )
    if is_qdii:
        # 尝试匹配跟踪的海外指数
        for pattern, benchmark, delay, desc in _QDII_BENCHMARK_RULES:
            if re.search(pattern, fund_name, re.IGNORECASE):
                return FundClassification(
                    fund_type=f"qdii_{benchmark}",
                    estimation_method="overseas_index",
                    benchmark_index=benchmark,
                    settlement_delay=delay,
                    description=desc,
                    fund_type_raw=fund_type_raw,
                )
        # 无法匹配具体指数 → 通用 QDII（默认用标普代理）
        return FundClassification(
            fund_type="qdii_global",
            estimation_method="overseas_index",
            benchmark_index="sp500",
            settlement_delay=2,
            description="QDII-海外",
            fund_type_raw=fund_type_raw,
        )

    # ── 2. 场内 ETF（代码 5x/1x 开头 + 6 位） ──
    if _is_etf_code_direct(fund_code) and ("ETF" in fund_name or "指数" in fund_type_raw):
        return FundClassification(
            fund_type="etf",
            estimation_method="etf_realtime",
            description="场内ETF",
            fund_type_raw=fund_type_raw,
        )

    # ── 3. ETF 联接基金（名称含 "联接" 或其他关键词） ──
    if "联接" in fund_name or ("ETF" in fund_name and not _is_etf_code_direct(fund_code)):
        return FundClassification(
            fund_type="etf_linked",
            estimation_method="etf_linked",
            description="ETF联接",
            fund_type_raw=fund_type_raw,
        )

    # ── 4. 普通股票 / 混合型 ──
    if any(t in fund_type_raw for t in ("股票型", "混合型", "指数型")):
        ft = "stock" if "股票" in fund_type_raw else "mixed"
        return FundClassification(
            fund_type=ft,
            estimation_method="weighted_holdings",
            description=fund_type_raw or ("股票型" if ft == "stock" else "混合型"),
            fund_type_raw=fund_type_raw,
        )

    # ── 5. 债券型 ──
    if "债券" in fund_type_raw:
        return FundClassification(
            fund_type="bond",
            estimation_method="nav_only",
            description="债券型",
            fund_type_raw=fund_type_raw,
        )

    # ── 6. 货币型 ──
    if "货币" in fund_type_raw:
        return FundClassification(
            fund_type="money",
            estimation_method="nav_only",
            description="货币型",
            fund_type_raw=fund_type_raw,
        )

    # ── 7. 兜底：用重仓股估值 ──
    return FundClassification(
        fund_type="other",
        estimation_method="weighted_holdings",
        description=fund_type_raw or "其他",
        fund_type_raw=fund_type_raw,
    )


# ── 辅助函数 ──

# 基金信息缓存 (name, type_raw) — 逐基金缓存
_info_cache: TTLCache = TTLCache(maxsize=3000, ttl=7200)

# 全量基金列表缓存（整个 DataFrame，2h 有效）
_fund_list_cache: dict = {"df": None, "ts": 0}
_FUND_LIST_TTL = 7200  # 2h


def _load_fund_list():
    """加载并缓存东方财富全量基金列表"""
    import time
    now = time.time()
    if _fund_list_cache["df"] is not None and (now - _fund_list_cache["ts"]) < _FUND_LIST_TTL:
        return _fund_list_cache["df"]
    try:
        import akshare as ak
        df = ak.fund_name_em()
        if df is not None and not df.empty:
            _fund_list_cache["df"] = df
            _fund_list_cache["ts"] = now
            logger.info("基金列表已加载: %d 只基金", len(df))
            return df
    except Exception as e:
        logger.warning("加载基金列表失败: %s", e)
        # 如果有旧缓存就继续用
        if _fund_list_cache["df"] is not None:
            return _fund_list_cache["df"]
    return None


def _get_fund_info(fund_code: str) -> tuple[str, str]:
    """获取基金名称 + 东方财富基金类型（带缓存）"""
    if fund_code in _info_cache:
        return _info_cache[fund_code]

    fund_name = fund_code
    fund_type_raw = ""

    fund_list = _load_fund_list()
    if fund_list is not None:
        matched = fund_list[fund_list["基金代码"] == fund_code]
        if not matched.empty:
            fund_name = str(matched.iloc[0]["基金简称"])
            fund_type_raw = str(matched.iloc[0]["基金类型"])

    # 如果东方财富列表中没找到，尝试从 fund_service 的名称缓存获取
    if fund_name == fund_code:
        try:
            from app.services.fund_service import get_fund_name
            name = get_fund_name(fund_code)
            if name and name != fund_code:
                fund_name = name
        except Exception:
            pass

    _info_cache[fund_code] = (fund_name, fund_type_raw)
    return fund_name, fund_type_raw


def _is_etf_code_direct(code: str) -> bool:
    """判断是否为场内 ETF 代码格式 (5xxxxx / 1xxxxx 6位)"""
    code = str(code).strip()
    if len(code) != 6:
        return False
    return code[:2] in ("51", "15", "56", "58", "52", "16")
