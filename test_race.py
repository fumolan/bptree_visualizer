# -*- coding: utf-8 -*-
"""树高对决模块测试:层数公式(整数精确)+ SVG 渲染冒烟"""
import sys
import warnings

sys.path.insert(0, r'D:\github\bptree_visualizer')
warnings.filterwarnings('ignore')
from bptree_visualizer import BPlusTree, bp_height, render_height_race, render_race_layout, render_tree, _fmt_cn, _levels

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
    # 摆放对照图冒烟:层数/页数标注要进图
    lsvg, lh = render_race_layout(n, m)
    assert lsvg.startswith('<svg') and lsvg.rstrip().endswith('</svg>') and lh > 100, f'n={n}: 摆放图异常'
    assert f'一共 {bp} 层' in lsvg or f'只要 {bp} 层' in lsvg, f'n={n}: 摆放图缺层数标注'
    leaf_pages = max(1, -(-n // m))
    assert _fmt_cn(leaf_pages) in lsvg, f'n={n} m={m}: 摆放图缺叶子页数 {_fmt_cn(leaf_pages)}'

# 中文数量级格式化
assert _fmt_cn(16_777_216) == '1678 万'
assert _fmt_cn(1_000_000_000) == '10 亿'
assert _fmt_cn(1024) == '1 千'
assert _fmt_cn(999) == '999'
assert _fmt_cn(10_000) == '1 万'
assert _fmt_cn(15_000) == '1.5 万'

# 多层树渲染冒烟:顺序插 80 行(阶 4)至少 3 层,渲染高度必须容纳所有内部层(回归:曾全部叠在一行)
t = BPlusTree(4)
for k in range(1, 81):
    t.insert_traced(k, (k, f'n{k}', 20))
n_levels = len(_levels(t.root))
assert n_levels >= 3, f'80 行应 >= 3 层,实际 {n_levels}'
snap = {'M': 4, 'root': t.root}
svg, h = render_tree(snap, None, 'c')          # 聚簇索引渲染(整型键)
assert svg.startswith('<svg') and svg.rstrip().endswith('</svg>'), 'c: 渲染异常'
assert h > 150 + 54 * (n_levels - 1), f'{n_levels} 层树渲染高度 {h} 容不下内部层'
t2 = BPlusTree(4)                               # 二级索引渲染(字符串键,同 app 用法)
for k in range(1, 81):
    t2.insert_traced(f'n{k}', k)
svg2, h2 = render_tree({'M': 4, 'root': t2.root}, None, 's')
assert svg2.startswith('<svg') and svg2.rstrip().endswith('</svg>') and h2 > 150 + 54 * (n_levels - 1), 's: 渲染异常'
print('RACE OK — 层数公式 7 组用例(含不等式验证)+ 两张 SVG 冒烟 + 三层树渲染 + 数量级格式化全部通过')
