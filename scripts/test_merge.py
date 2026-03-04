"""
测试两行基金名称合并逻辑
模拟支付宝截图的 OCR 文本块布局
"""
import sys, re
sys.path.insert(0, '.')
from app.services.ocr_service import (
    _is_fund_name, _looks_like_name_fragment, _is_noise_text,
    _clean_fund_name, _is_number_text, _is_percent_text
)

line_h = 30

# 模拟支付宝截图中左列的所有文本块
all_left = [
    # 基金1: 泰信优势领航混 + 合C
    {'text': '泰信优势领航混', 'cx': 80, 'cy': 100, 'lx': 20, 'rx': 145, 'ty': 85, 'by': 115, 'h': 30, 'conf': 0.95},
    {'text': '合C',           'cx': 40, 'cy': 132, 'lx': 20, 'rx': 60,  'ty': 117, 'by': 147, 'h': 30, 'conf': 0.90},
    # 基金2: 永赢先进制造智 + 选混合C
    {'text': '永赢先进制造智', 'cx': 80, 'cy': 300, 'lx': 20, 'rx': 145, 'ty': 285, 'by': 315, 'h': 30, 'conf': 0.95},
    {'text': '选混合C',       'cx': 60, 'cy': 332, 'lx': 20, 'rx': 100, 'ty': 317, 'by': 347, 'h': 30, 'conf': 0.92},
    # 基金3: 华夏有色金属 + ETF联接C + 噪声
    {'text': '华夏有色金属',   'cx': 70, 'cy': 500, 'lx': 20, 'rx': 130, 'ty': 485, 'by': 515, 'h': 30, 'conf': 0.95},
    {'text': 'ETF联接C',      'cx': 60, 'cy': 532, 'lx': 20, 'rx': 110, 'ty': 517, 'by': 547, 'h': 30, 'conf': 0.91},
    {'text': '金选指数基金',   'cx': 70, 'cy': 570, 'lx': 20, 'rx': 130, 'ty': 555, 'by': 585, 'h': 30, 'conf': 0.80},
    {'text': '市场解读',       'cx': 70, 'cy': 610, 'lx': 20, 'rx': 100, 'ty': 595, 'by': 625, 'h': 30, 'conf': 0.85},
    {'text': '关税风波再起',   'cx': 100, 'cy': 610, 'lx': 65, 'rx': 145, 'ty': 595, 'by': 625, 'h': 30, 'conf': 0.85},
    # 基金4: 永赢国证商用卫 + 星通信产业ET
    {'text': '永赢国证商用卫', 'cx': 80, 'cy': 700, 'lx': 20, 'rx': 145, 'ty': 685, 'by': 715, 'h': 30, 'conf': 0.95},
    {'text': '星通信产业ET',   'cx': 70, 'cy': 732, 'lx': 20, 'rx': 130, 'ty': 717, 'by': 747, 'h': 30, 'conf': 0.93},
    # 基金5: 永赢高端装备智 + 选混合C
    {'text': '永赢高端装备智', 'cx': 80, 'cy': 900, 'lx': 20, 'rx': 145, 'ty': 885, 'by': 915, 'h': 30, 'conf': 0.95},
    {'text': '选混合C',       'cx': 60, 'cy': 932, 'lx': 20, 'rx': 100, 'ty': 917, 'by': 947, 'h': 30, 'conf': 0.92},
]

# 新逻辑: 收集所有非噪声/非数字文本块
left_text_blocks = []
for b in all_left:
    t = _clean_fund_name(b['text'])
    if not t:
        continue
    if _is_noise_text(t):
        continue
    if _is_number_text(t) or _is_percent_text(t):
        continue
    left_text_blocks.append(b)
left_text_blocks.sort(key=lambda b: b['cy'])

filtered = [b['text'] for b in left_text_blocks]
print('过滤后的文本块:', filtered)

# 合并逻辑
merged_names = []
i = 0
while i < len(left_text_blocks):
    block = left_text_blocks[i]
    name = _clean_fund_name(block['text'])
    if not _is_fund_name(name):
        i += 1
        continue
    ty = block['ty']
    by = block['by']
    lh = block['h']
    base_lx = block['lx']
    while i + 1 < len(left_text_blocks):
        next_b = left_text_blocks[i + 1]
        next_text = _clean_fund_name(next_b['text'])
        gap = next_b['ty'] - by
        aligned = abs(next_b['lx'] - base_lx) <= max(24, lh * 2)
        is_class_only = bool(re.fullmatch(r'[A-EHa-eh]', next_text or ''))
        merge_gap_limit = lh * (2.4 if is_class_only else 1.8)
        if gap < merge_gap_limit and aligned and _looks_like_name_fragment(next_text):
            name += next_text
            by = next_b['by']
            i += 1
        else:
            break
    name = _clean_fund_name(name)
    if _is_fund_name(name):
        merged_names.append(name)
    i += 1

# 验证结果
expected = [
    '泰信优势领航混合C',
    '永赢先进制造智选混合C',
    '华夏有色金属ETF联接C',
    '永赢国证商用卫星通信产业ET',
    '永赢高端装备智选混合C',
]

print('\n合并结果:')
all_pass = True
for idx, name in enumerate(merged_names):
    exp = expected[idx] if idx < len(expected) else '???'
    ok = name == exp
    if not ok:
        all_pass = False
    print('  %d. [%s] expect=[%s] %s' % (idx+1, name, exp, 'OK' if ok else 'FAIL'))

if len(merged_names) != len(expected):
    all_pass = False
    print('数量不匹配: got %d, expected %d' % (len(merged_names), len(expected)))

print('\n>>> %s' % ('ALL TESTS PASSED!' if all_pass else 'SOME TESTS FAILED'))
