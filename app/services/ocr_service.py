"""
OCR 识别支付宝持仓截图并解析基金数据

流程:
  1. 用户上传支付宝基金持仓页截图
  2. RapidOCR 识别所有文本块（含坐标）
  3. 按空间位置聚类为"行"，再按列分区提取 基金名称 / 市值 / 持有收益
  4. 通过 akshare fund_name_em() 将基金名称映射到 6 位基金代码
  5. 返回结构化列表供前端确认后批量导入
"""
import re
import time
import logging
from difflib import SequenceMatcher
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

# ── 全局单例 ──────────────────────────────

_ocr_engine = None
_fund_map_cache: dict[str, str] | None = None
_fund_map_time: float = 0
_FUND_MAP_TTL = 3600  # 1h


def _get_engine():
    """Lazy-init RapidOCR engine"""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
            logger.info("RapidOCR 引擎初始化成功")
        except ImportError:
            raise RuntimeError(
                "请先安装 rapidocr-onnxruntime: pip install rapidocr-onnxruntime==1.2.3"
            )
    return _ocr_engine


def warmup_ocr_engine():
    """应用启动时预热 OCR 引擎，避免首次请求时耗时初始化"""
    try:
        _get_engine()
        logger.info("OCR 引擎预热完成")
    except Exception as e:
        logger.warning(f"OCR 引擎预热失败（将在首次使用时重试）: {e}")


# ═══════════════════════════════════════════
#  基金名称 → 代码 映射
# ═══════════════════════════════════════════

def _get_fund_name_map() -> dict[str, str]:
    """获取 基金简称→基金代码 映射表（1h TTL 缓存）"""
    global _fund_map_cache, _fund_map_time
    now = time.time()
    if _fund_map_cache and (now - _fund_map_time) < _FUND_MAP_TTL:
        return _fund_map_cache

    try:
        import akshare as ak
        df = ak.fund_name_em()
        mapping: dict[str, str] = {}
        for _, row in df.iterrows():
            name = str(row.get("基金简称", "")).strip()
            code = str(row.get("基金代码", "")).strip()
            if name and code and len(code) == 6:
                mapping[name] = code
        _fund_map_cache = mapping
        _fund_map_time = now
        logger.info(f"基金名称映射表已加载: {len(mapping)} 条")
        return mapping
    except Exception as e:
        logger.error(f"获取基金名称映射失败: {e}")
        return _fund_map_cache or {}


def _match_fund_code(ocr_name: str, name_map: dict[str, str]) -> tuple[str | None, str]:
    """
    将 OCR 识别的基金名称匹配到基金代码。
    返回 (code, matched_official_name)；匹配失败返回 (None, ocr_name)。
    """
    ocr_name = _clean_fund_name(ocr_name)
    if not ocr_name:
        return None, ocr_name

    # 1. 精确匹配
    if ocr_name in name_map:
        return name_map[ocr_name], ocr_name

    normalized_official = [
        (
            official_name,
            code,
            _normalize_for_match(official_name),
            _normalize_for_match(official_name, drop_class_suffix=True),
        )
        for official_name, code in name_map.items()
    ]

    ocr_norm = _normalize_for_match(ocr_name)
    ocr_norm_no_cls = _normalize_for_match(ocr_name, drop_class_suffix=True)
    ocr_class = _extract_share_class(ocr_name)

    # 1.1 归一化后精确匹配
    for official_name, code, off_norm, _ in normalized_official:
        if off_norm == ocr_norm:
            return code, official_name

    # 2. 包含匹配（选最长的匹配名称）
    best_code, best_name, best_score = None, ocr_name, (-1, -1)
    for official_name, code, off_norm, _ in normalized_official:
        # 双向包含
        if official_name in ocr_name or ocr_name in official_name or off_norm in ocr_norm or ocr_norm in off_norm:
            # 先看份额类别一致性，再比较匹配长度
            official_class = _extract_share_class(official_name)
            class_bonus = 2 if (ocr_class and official_class == ocr_class) else 1 if (ocr_class is None and official_class == 'C') else 0
            score = (class_bonus, min(len(official_name), len(ocr_name)))
            if score > best_score:
                best_code, best_name, best_score = code, official_name, score

    if best_code:
        return best_code, best_name

    # 3. 去掉尾部 A/B/C/E/H 再试
    if ocr_norm_no_cls and ocr_norm_no_cls != ocr_norm:
        same_root = []
        for official_name, code, _, off_norm_no_cls in normalized_official:
            if ocr_norm_no_cls == off_norm_no_cls:
                same_root.append((official_name, code))
        if same_root:
            same_root.sort(key=lambda x: _share_class_priority(_extract_share_class(x[0])), reverse=True)
            return same_root[0][1], same_root[0][0]

    # 4. 模糊匹配（处理少字、错字、OCR 污染）
    if len(ocr_norm_no_cls) >= 4:
        best_ratio = 0.0
        best = None
        for official_name, code, _, off_norm_no_cls in normalized_official:
            if not off_norm_no_cls:
                continue
            ratio = SequenceMatcher(None, ocr_norm_no_cls, off_norm_no_cls).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = (official_name, code)
            elif ratio == best_ratio and best is not None:
                cur_priority = _share_class_priority(_extract_share_class(official_name))
                best_priority = _share_class_priority(_extract_share_class(best[0]))
                if ocr_class:
                    if _extract_share_class(official_name) == ocr_class and _extract_share_class(best[0]) != ocr_class:
                        best = (official_name, code)
                elif cur_priority > best_priority:
                    best = (official_name, code)
        if best and best_ratio >= 0.82:
            return best[1], best[0]

    return None, ocr_name


# ═══════════════════════════════════════════
#  文本分类工具
# ═══════════════════════════════════════════

# 排除的噪声文本
_NOISE_TEXTS = frozenset([
    '我的持有', '更新时间排序', '全部', '偏股', '偏债', '指数', '黄金',
    '基金市场', '机会', '自选', '持有', '名称', '金额', '收益',
    '金额/昨日收益', '持有收益/率', '金选', '指数基金', '混合基金',
    '偏股基金', '偏债基金', '债券基金', '市场解读', '更新时间',
    '昨日收益', '持有收益', '收益率', '排序',
    # 短噪声标签（防止被误合并进基金名称）
    '关税风波再起', '金价强势表现',
])

_NOISE_KEYWORDS = (
    '金选指数基金',
    '金选指数',
    '市场解读',
    '更新时间排序',
    '金额昨日收益',
    '持有收益率',
    '我的持有',
    '关税风波',
    '金价强势',
    '还有哪些',
)

_NOISE_TEXTS_NORMALIZED = frozenset(
    re.sub(r'[“”"\'`~!！@#￥%^&*()（）\[\]【】{}<>《》,，.。:：;；|\\/?？·•…\s]+', '', x)
    for x in _NOISE_TEXTS
)


def _normalize_text(text: str) -> str:
    text = str(text or '').strip()
    text = text.replace(' ', '').replace('\u3000', '')
    text = re.sub(r'[“”"\'`~!！@#￥%^&*()（）\[\]【】{}<>《》,，.。:：;；|\\/?？·•…]+', '', text)
    return text


def _is_noise_text(text: str) -> bool:
    raw = str(text or '').strip()
    norm = _normalize_text(raw)
    if not norm:
        return True
    if raw in _NOISE_TEXTS or norm in _NOISE_TEXTS_NORMALIZED:
        return True
    for kw in _NOISE_KEYWORDS:
        if _normalize_text(kw) in norm:
            return True
    return False


def _clean_fund_name(text: str) -> str:
    name = str(text or '').strip()
    name = re.sub(r'金选指数基金.*$', '', name)
    name = re.sub(r'市场解读.*$', '', name)
    name = re.sub(r'[?？!！,，.。…⊙●◎○☆★◇◆□■▲△▼▽]+$', '', name)
    return name.strip()


def _normalize_for_match(text: str, drop_class_suffix: bool = False) -> str:
    s = _normalize_text(_clean_fund_name(text)).lower()
    if drop_class_suffix:
        s = re.sub(r'[a-eh]$', '', s)
    return s


def _extract_share_class(text: str) -> str | None:
    normalized = _normalize_text(text).upper().replace('Ａ', 'A').replace('Ｂ', 'B').replace('Ｃ', 'C').replace('Ｅ', 'E').replace('Ｈ', 'H')
    if not normalized:
        return None
    m = re.search(r'([A-EH])$', normalized)
    return m.group(1) if m else None


def _share_class_priority(share_class: str | None) -> int:
    # 默认优先级：C > A > E > H > B；None 最低
    order = {'C': 5, 'A': 4, 'E': 3, 'H': 2, 'B': 1}
    return order.get((share_class or '').upper(), 0)


def _looks_like_name_fragment(text: str) -> bool:
    t = _clean_fund_name(text)
    if not t:
        return False
    if _is_noise_text(t):
        return False
    if _is_number_text(t) or _is_percent_text(t):
        return False
    if re.search(r'\d', t):
        return False
    has_cn = any('\u4e00' <= c <= '\u9fff' for c in t)
    has_word = bool(re.search(r'[A-Za-z]+', t))
    return has_cn or has_word


def _is_fund_name(text: str) -> bool:
    """判断文本是否像基金名称"""
    text = _clean_fund_name(text)
    if len(text) < 4:
        return False
    # 存在于噪声列表
    if _is_noise_text(text):
        return False
    # 至少 3 个中文字符
    cn_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cn_count < 3:
        return False
    # 不能是纯数字开头
    if text[0].isdigit():
        return False
    # 不能是"市场解读"开头
    if text.startswith('市场解读') or text.startswith('还有哪些'):
        return False
    return True


def _parse_number(text: str) -> float | None:
    """解析数字文本（支持千分位逗号、+/- 号、% 后缀）"""
    text = text.strip().replace(',', '').replace('，', '').replace(' ', '')
    text = text.rstrip('%').rstrip('％')
    try:
        return float(text)
    except ValueError:
        return None


def _is_number_text(text: str) -> bool:
    return _parse_number(text) is not None


def _is_percent_text(text: str) -> bool:
    t = text.strip()
    return t.endswith('%') or t.endswith('％')


# ═══════════════════════════════════════════
#  图片预处理
# ═══════════════════════════════════════════

def _preprocess_image(image_bytes: bytes) -> bytes:
    """缩放大图以加速 OCR（限长边 2000px）"""
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        max_side = max(img.size)
        if max_side > 2000:
            ratio = 2000 / max_side
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
    except Exception:
        pass
    return image_bytes


# ═══════════════════════════════════════════
#  核心解析逻辑
# ═══════════════════════════════════════════

def parse_alipay_screenshot(image_bytes: bytes) -> list[dict[str, Any]]:
    """
    解析支付宝持仓截图。

    返回:
      [
        {
          "name": "华宝中证金融科技主题ETF联接C",
          "code": "007871",                # 匹配到的基金代码 (可能为 null)
          "matched_name": "华宝中证金融科...", # 匹配到的官方名称
          "market_value": 1631.94,
          "total_profit": -119.36,
          "profit_rate": -6.82,
          "daily_profit": -45.44,
        },
        ...
      ]
    """
    engine = _get_engine()

    image_bytes = _preprocess_image(image_bytes)

    result, elapse = engine(image_bytes)
    if not result:
        logger.info("OCR 未识别到任何文本")
        return []

    logger.info(f"OCR 识别到 {len(result)} 个文本块, 耗时 {elapse}")

    # ── 提取文本块 + 坐标 ──
    blocks = []
    for item in result:
        bbox, text, conf = item
        text = text.strip()
        if not text:
            continue
        cy = sum(p[1] for p in bbox) / 4
        cx = sum(p[0] for p in bbox) / 4
        lx = min(p[0] for p in bbox)
        rx = max(p[0] for p in bbox)
        ty = min(p[1] for p in bbox)
        by = max(p[1] for p in bbox)
        blocks.append({
            "text": text,
            "cx": cx, "cy": cy,
            "lx": lx, "rx": rx,
            "ty": ty, "by": by,
            "h": by - ty,
            "conf": conf,
        })

    if not blocks:
        return []

    # ── 确定图片宽度/高度 ──
    img_w = max(b["rx"] for b in blocks)

    # ── 三列分区 ──
    # 支付宝布局: 左~38% = 名称, 中38%~63% = 金额列, 右63%+ = 收益列
    col_mid_start = img_w * 0.38
    col_right_start = img_w * 0.63

    left_blocks = [b for b in blocks if b["cx"] < col_mid_start]
    mid_blocks = [b for b in blocks if col_mid_start <= b["cx"] < col_right_start]
    right_blocks = [b for b in blocks if b["cx"] >= col_right_start]

    # ── 在左列收集所有非噪声/非数字文本块（含碎片）──
    # 重要：不能仅用 _is_fund_name 过滤，否则短碎片如 "合C"、"ETF联接C"
    # 会被排除，导致无法与上一行合并
    left_text_blocks = []
    for b in left_blocks:
        t = _clean_fund_name(b["text"])
        if not t:
            continue
        if _is_noise_text(t):
            continue
        if _is_number_text(t) or _is_percent_text(t):
            continue
        left_text_blocks.append(b)
    left_text_blocks.sort(key=lambda b: b["cy"])

    # ── 合并分行的基金名称 ──
    # OCR 可能把一个长名称拆成两行, 如 "泰信优势领航混" + "合C"
    # 或 "华夏有色金属" + "ETF联接C"
    # 第二行碎片可能不满足 _is_fund_name，但仍需合并到前一行
    merged_names: list[dict[str, Any]] = []
    i = 0
    while i < len(left_text_blocks):
        block = left_text_blocks[i]
        name = _clean_fund_name(block["text"])

        # 只从看起来像完整基金名称的块开始一个新条目
        if not _is_fund_name(name):
            i += 1
            continue

        ty = block["ty"]
        by = block["by"]
        line_h = block["h"]
        base_lx = block["lx"]

        # 检查后续的块是否是同基金名称的续行
        while i + 1 < len(left_text_blocks):
            next_b = left_text_blocks[i + 1]
            next_text = _clean_fund_name(next_b["text"])
            gap = next_b["ty"] - by
            aligned = abs(next_b["lx"] - base_lx) <= max(24, line_h * 2)
            is_class_only_line = bool(re.fullmatch(r'[A-EHa-ehＡ-ＥＨａ-ｅｈ]', next_text or ''))
            merge_gap_limit = line_h * (2.4 if is_class_only_line else 1.8)

            if gap < merge_gap_limit and aligned and _looks_like_name_fragment(next_text):
                name += next_text
                by = next_b["by"]
                i += 1
            else:
                break

        name = _clean_fund_name(name)
        if not _is_fund_name(name):
            i += 1
            continue

        merged_names.append({
            "name": name,
            "ty": ty,
            "by": by,
            "cy": (ty + by) / 2,
        })
        i += 1

    logger.info(f"识别到 {len(merged_names)} 个基金名称: "
                f"{[n['name'] for n in merged_names]}")

    # ── 加载基金名称映射 ──
    name_map = _get_fund_name_map()

    # ── 为每个基金提取数字 ──
    funds: list[dict[str, Any]] = []
    for idx, fn in enumerate(merged_names):
        # 确定该基金的 Y 范围
        y_start = fn["ty"] - 10
        if idx + 1 < len(merged_names):
            y_end = merged_names[idx + 1]["ty"] - 10
        else:
            y_end = fn["by"] + 200

        # ── 中列数字（金额 / 昨日收益）──
        mid_nums = sorted(
            [b for b in mid_blocks
             if y_start <= b["cy"] <= y_end and _is_number_text(b["text"])],
            key=lambda b: b["cy"],
        )

        # ── 右列数字（持有收益 / 持有收益率）──
        right_nums = sorted(
            [b for b in right_blocks
             if y_start <= b["cy"] <= y_end and _is_number_text(b["text"])],
            key=lambda b: b["cy"],
        )

        # 中列: 第一个 = 市值（正数）, 第二个 = 昨日收益
        market_value = None
        daily_profit = None
        for j, b in enumerate(mid_nums):
            val = _parse_number(b["text"])
            if val is None:
                continue
            if j == 0:
                market_value = abs(val)  # 市值一定是正数
            elif j == 1:
                daily_profit = val

        # 右列: 非% = 持有收益, % = 持有收益率
        total_profit = None
        profit_rate = None
        for b in right_nums:
            if _is_percent_text(b["text"]):
                profit_rate = _parse_number(b["text"])
            else:
                if total_profit is None:
                    total_profit = _parse_number(b["text"])

        # ── 匹配基金代码 ──
        code, matched_name = _match_fund_code(fn["name"], name_map)

        # ── 只保留有市值的条目 ──
        if market_value and market_value > 0:
            funds.append({
                "name": fn["name"],
                "code": code,
                "matched_name": matched_name if code else None,
                "market_value": round(market_value, 2),
                "total_profit": round(total_profit, 2) if total_profit is not None else None,
                "profit_rate": round(profit_rate, 2) if profit_rate is not None else None,
                "daily_profit": round(daily_profit, 2) if daily_profit is not None else None,
            })

    logger.info(f"成功解析 {len(funds)} 只基金: "
                f"{[(f['name'], f['code']) for f in funds]}")
    return funds
