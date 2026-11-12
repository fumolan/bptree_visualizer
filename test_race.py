# -*- coding: utf-8 -*-
"""树高对决模块测试:层数公式(整数精确)+ SVG 渲染冒烟"""
import sys
import warnings

sys.path.insert(0, r'D:\github\bptree_visualizer')
warnings.filterwarnings('ignore')
from bptree_visualizer import bp_height, render_height_race, _fmt_cn

# 层数公式:与手算对照,并用不等式验证"少一层必装不下、当前层必装得下"
cases = [
    (1_000, 1000, 10, 1),
    (10_000, 1000, 14, 2),
    (1_000_000, 1000, 20, 2),
    (10_000_000, 1000, 24, 3),
    (10_000_000, 100, 24, 4),
    (100_000_000, 1000, 27, 3),
    (100_000_000, 10, 27, 8),
]
for n, m, rb_want, bp_want in cases:
    rb = n.bit_length()
    bp = bp_height(n, m)
    assert rb == rb_want, f'n={n}: 红黑树层数 {rb} != {rb_want}'
    assert bp == bp_want, f'n={n} m={m}: B+ 层数 {bp} != {bp_want}'
    assert 2 ** (rb - 1) - 1 < n <= 2 ** rb - 1, f'n={n}: 红黑树层数不等式不成立'
    assert m ** (bp - 1) < n <= m ** bp, f'n={n} m={m}: B+ 层数不等式不成立'
    svg, h = render_height_race(n, m)
    assert svg.startswith('<svg') and svg.rstrip().endswith('</svg>') and h > 100, f'n={n}: SVG 异常'
    assert f'树高 {bp} 层' in svg and f'树高 {rb} 层' in svg, f'n={n}: SVG 缺标题文字'

# 中文数量级格式化
assert _fmt_cn(16_777_216) == '1678 万'
assert _fmt_cn(1_000_000_000) == '10 亿'
assert _fmt_cn(1024) == '1 千'
assert _fmt_cn(999) == '999'
print('RACE OK — 层数公式 7 组用例(含不等式验证)+ SVG 冒烟 + 数量级格式化全部通过')
