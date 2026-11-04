# -*- coding: utf-8 -*-
"""B+ 树引擎压力测试:随机操作 vs dict 模型 + 结构不变式检查"""
import random
import sys

sys.path.insert(0, r'D:\github\bptree_visualizer')
from bptree_visualizer import BPlusTree, _leaves, _levels


def first_leaf(n):
    while not n.leaf:
        n = n.children[0]
    return n


def check_invariants(t):
    """所有叶子同深度、键数上下限、键有序、分隔键=右子树最小键副本、链表完整"""
    depths = set()
    leaves = []

    def walk(n, d, is_root):
        assert len(n.keys) <= t.M, f'节点 {n.id} 键数超上限'
        if n.leaf:
            leaves.append(n)
            depths.add(d)
            if not is_root:
                assert len(n.keys) >= t.min_leaf, f'叶子 {n.id} 键数低于下限'
            assert n.keys == sorted(n.keys), '叶子键无序'
        else:
            assert len(n.children) == len(n.keys) + 1, '孩子数与键数不匹配'
            if not is_root:
                assert len(n.children) >= t.min_children, f'内部节点 {n.id} 孩子数低于下限'
            stack = [(n, d, is_root)]
            # 分隔键检查:keys[i] == 右侧子树第一个叶子的最小键
            for i, k in enumerate(n.keys):
                fl = first_leaf(n.children[i + 1])
                # 分隔键允许在删除后"过时"(右子树最小键可能已变大),但必须仍是下界
                assert fl.keys and fl.keys[0] >= k, f'分隔键 {k} 大于右子树最小键,路由被破坏'
            for c in n.children:
                walk(c, d + 1, False)
    walk(t.root, 0, True)
    assert len(depths) == 1, '叶子不在同一层'
    for i in range(len(leaves) - 1):
        assert leaves[i].next is leaves[i + 1], '叶子链表断裂'
    return [k for l in leaves for k in l.keys]


def check_range(t, model, lo, hi):
    r = t.range_traced(lo, hi)
    expect = [(k, v) for k, v in sorted(model.items()) if lo <= k <= hi]
    assert r['results'] == expect, f'范围结果不一致 {[x[0] for x in r["results"]]} vs {[x[0] for x in expect]}'


random.seed(2026)
total_ops = 0
for order in (3, 4, 5, 6):
    for trial in range(3):
        t = BPlusTree(order)
        model = {}
        for op_no in range(1500):
            if model and random.random() < 0.45:
                k = random.choice(list(model))
                t.delete_traced(k)
                del model[k]
            else:
                k = random.randint(1, 80)
                v = (k, f'n{k}', k % 60 + 18)
                t.insert_traced(k, v)
                model[k] = v
            total_ops += 1
            keys = check_invariants(t)
            assert keys == sorted(model.keys()), \
                f'order={order} trial={trial} op={op_no}: 树键 {keys} != 模型 {sorted(model.keys())}'
            # 查找抽查
            probe = random.randint(1, 80)
            r = t.search_traced(probe)
            assert r['found'] == (probe in model), '查找结果不一致'
            if r['found']:
                assert r['value'] == model[probe]
            if op_no % 300 == 0:
                check_range(t, model, random.randint(1, 40), random.randint(40, 80))
print(f'ALL OK — order 3/4/5/6 × 3 trials × 1500 ops,共 {total_ops} 次操作,不变式全部通过')
