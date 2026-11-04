# -*- coding: utf-8 -*-
"""
bptree_visualizer —— B+ 树可视化演示(单文件 Streamlit 应用,结构对标 cnn_visualizer)

Python 负责:
  1. B+ 树引擎:插入/删除/查找/范围查询,含页分裂、键上浮、借键、合并、根收缩
  2. 步骤编排:每个操作拆成可逐步回放的叙述步骤(定位 → 写入/分裂 → 回表 ...)
  3. 页面渲染:把两棵 B+ 树(聚簇索引 + 二级索引)画成 SVG,拼装成 HTML

运行:
  .venv\\Scripts\\python.exe -m streamlit run bptree_visualizer.py
"""
from __future__ import annotations

import copy
import html as _html
import random
import time

import streamlit as st
import streamlit.components.v1 as components

# ============================================================
# 1. B+ 树引擎(每个节点最多 M 个键;叶子用 next 指针串成链表)
# ============================================================
class Node:
    _nid = 0

    def __init__(self, leaf):
        Node._nid += 1
        self.id = Node._nid
        self.leaf = leaf
        self.keys = []        # 叶子:数据键;内部节点:路标键
        self.values = []      # 叶子专属:与 keys 一一对应
        self.children = []    # 内部节点专属
        self.parent = None
        self.next = None      # 叶子链表


class BPlusTree:
    def __init__(self, order):
        self.M = order                      # 每页最多键数
        self.min_leaf = (order + 1) // 2    # 叶子页最少键数
        self.min_children = (order + 2) // 2  # 内部节点最少孩子数
        self.root = Node(True)
        self._root_grew = False

    def snap(self):
        return {'M': self.M, 'root': copy.deepcopy(self.root)}

    def find_path(self, key):
        path = [self.root]
        n = self.root
        while not n.leaf:
            i = 0
            while i < len(n.keys) and key >= n.keys[i]:
                i += 1
            n = n.children[i]
            path.append(n)
        return path

    # ---------- 插入(带步骤记录) ----------
    def insert_traced(self, key, value):
        self._root_grew = False
        steps = []
        path = self.find_path(key)
        leaf = path[-1]
        steps.append({'phase': 'locate', 'key': key,
                      'path': [n.id for n in path], 'leaf': leaf.id,
                      'root_keys': list(self.root.keys), 'snap': self.snap()})
        i = 0
        while i < len(leaf.keys) and key > leaf.keys[i]:
            i += 1
        if i < len(leaf.keys) and leaf.keys[i] == key:
            leaf.values[i] = value
            steps.append({'phase': 'update', 'key': key, 'split': None, 'snap': self.snap()})
            return steps
        leaf.keys.insert(i, key)
        leaf.values.insert(i, value)
        split = None
        if len(leaf.keys) > self.M:
            split = self._split_leaf(leaf)
            split['root_grow'] = self._root_grew
        steps.append({'phase': 'write', 'key': key, 'split': split, 'snap': self.snap()})
        return steps

    def _split_leaf(self, leaf):
        right = Node(True)
        mid = (self.M + 1) // 2
        right.keys = leaf.keys[mid:]
        right.values = leaf.values[mid:]
        leaf.keys = leaf.keys[:mid]
        leaf.values = leaf.values[:mid]
        right.next = leaf.next
        leaf.next = right
        right.parent = leaf.parent
        sep = right.keys[0]
        self._insert_in_parent(leaf, sep, right)
        return {'left': leaf.id, 'right': right.id, 'sep': sep}

    def _insert_in_parent(self, left, sep, right):
        if left is self.root:
            r = Node(False)
            r.keys = [sep]
            r.children = [left, right]
            left.parent = r
            right.parent = r
            self.root = r
            self._root_grew = True
            return
        p = left.parent
        i = p.children.index(left)
        p.keys.insert(i, sep)
        p.children.insert(i + 1, right)
        right.parent = p
        if len(p.keys) > self.M:
            self._split_internal(p)

    def _split_internal(self, node):
        right = Node(False)
        mid = (self.M + 1) // 2
        up = node.keys[mid]
        right.keys = node.keys[mid + 1:]
        right.children = node.children[mid + 1:]
        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]
        for c in right.children:
            c.parent = right
        right.parent = node.parent
        self._insert_in_parent(node, up, right)

    # ---------- 删除(带步骤记录:借键 / 合并 / 根收缩) ----------
    def delete_traced(self, key):
        steps = []
        path = self.find_path(key)
        leaf = path[-1]
        if key not in leaf.keys:
            steps.append({'phase': 'miss', 'key': key,
                          'path': [n.id for n in path], 'snap': self.snap()})
            return steps
        steps.append({'phase': 'locate', 'key': key,
                      'path': [n.id for n in path], 'leaf': leaf.id,
                      'root_keys': list(self.root.keys), 'snap': self.snap()})
        i = leaf.keys.index(key)
        leaf.keys.pop(i)
        leaf.values.pop(i)
        steps.append({'phase': 'remove', 'key': key, 'leaf': leaf.id, 'snap': self.snap()})
        self._fix_underflow(leaf, steps)
        if not self.root.leaf and len(self.root.children) == 1:
            self.root = self.root.children[0]
            self.root.parent = None
            steps.append({'phase': 'root_shrink', 'snap': self.snap()})
        return steps

    def _underflow(self, n):
        if n is self.root:
            return False
        need = self.min_leaf if n.leaf else self.min_children - 1
        return len(n.keys) < need

    def _fix_underflow(self, node, steps):
        while node is not self.root and self._underflow(node):
            p = node.parent
            i = p.children.index(node)
            need = self.min_leaf if node.leaf else self.min_children - 1
            pre = self.snap()  # 修复前快照:被合并的页在这之后会消失,页号要用它解析
            if i > 0 and len(p.children[i - 1].keys) > need:
                sib = p.children[i - 1]
                if node.leaf:
                    node.keys.insert(0, sib.keys.pop())
                    node.values.insert(0, sib.values.pop())
                    p.keys[i - 1] = node.keys[0]
                else:
                    c = sib.children.pop()
                    k_up = sib.keys.pop()
                    node.keys.insert(0, p.keys[i - 1])
                    node.children.insert(0, c)
                    c.parent = node
                    p.keys[i - 1] = k_up
                steps.append({'phase': 'borrow', 'dir': 'left', 'node': node.id,
                              'sib': sib.id, 'snap': self.snap(), 'pre_snap': pre})
                return
            if i < len(p.children) - 1 and len(p.children[i + 1].keys) > need:
                sib = p.children[i + 1]
                if node.leaf:
                    node.keys.append(sib.keys.pop(0))
                    node.values.append(sib.values.pop(0))
                    p.keys[i] = sib.keys[0]
                else:
                    c = sib.children.pop(0)
                    k_up = sib.keys.pop(0)
                    node.keys.append(p.keys[i])
                    node.children.append(c)
                    c.parent = node
                    p.keys[i] = k_up
                steps.append({'phase': 'borrow', 'dir': 'right', 'node': node.id,
                              'sib': sib.id, 'snap': self.snap(), 'pre_snap': pre})
                return
            # 兄弟都在下限:合并(优先左)
            if i > 0:
                sib = p.children[i - 1]
                if node.leaf:
                    sib.keys += node.keys
                    sib.values += node.values
                    sib.next = node.next
                else:
                    sib.keys.append(p.keys[i - 1])
                    sib.keys += node.keys
                    sib.children += node.children
                    for c in node.children:
                        c.parent = sib
                p.keys.pop(i - 1)
                p.children.pop(i)
                steps.append({'phase': 'merge', 'node': node.id, 'sib': sib.id,
                              'snap': self.snap(), 'pre_snap': pre})
                node = p
            else:
                sib = p.children[i + 1]
                if node.leaf:
                    node.keys += sib.keys
                    node.values += sib.values
                    node.next = sib.next
                else:
                    node.keys.append(p.keys[i])
                    node.keys += sib.keys
                    node.children += sib.children
                    for c in sib.children:
                        c.parent = node
                p.keys.pop(i)
                p.children.pop(i + 1)
                steps.append({'phase': 'merge', 'node': node.id, 'sib': sib.id,
                              'snap': self.snap(), 'pre_snap': pre})
                node = p

    # ---------- 查找 / 范围(带步骤记录) ----------
    def search_traced(self, key):
        path = self.find_path(key)
        leaf = path[-1]
        found = key in leaf.keys
        idx = leaf.keys.index(key) if found else None
        return {'path': [n.id for n in path], 'leaf': leaf.id, 'found': found,
                'value': leaf.values[idx] if found else None,
                'root_keys': list(self.root.keys), 'snap': self.snap()}

    def range_traced(self, lo, hi):
        path = self.find_path(lo)
        leaf = path[-1]
        results = []
        pages = [leaf.id]
        i = 0
        while i < len(leaf.keys) and leaf.keys[i] < lo:
            i += 1
        cur = leaf
        start_i = i
        stop = False
        while cur and not stop:
            j = start_i if cur is leaf else 0
            start_i = 0
            while j < len(cur.keys):
                k = cur.keys[j]
                if k > hi:
                    stop = True
                    break
                if k >= lo:
                    results.append((k, cur.values[j]))
                j += 1
            if stop:
                break
            if cur.keys and cur.keys[-1] > hi:
                break
            if cur.next is None:
                break
            cur = cur.next
            pages.append(cur.id)
        return {'path': [n.id for n in path], 'leaf': leaf.id, 'pages': pages,
                'results': results, 'root_keys': list(self.root.keys), 'snap': self.snap()}


# ============================================================
# 2. Demo:双树(聚簇索引 + 二级索引)+ 中文叙述编排
# ============================================================
class Demo:
    NAMES = ['Hana', 'Ivy', 'Jack', 'Kate', 'Liam', 'Mona', 'Noah', 'Olive', 'Pete',
             'Queen', 'Rose', 'Sam', 'Tom', 'Uma', 'Vivi', 'Wendy', 'Yuki', 'Zoe']

    def __init__(self, order=4):
        self.M = order
        self.pk = BPlusTree(order)   # 聚簇索引:叶子存整行 (id, name, age)
        self.sec = BPlusTree(order)  # 二级索引:叶子只存 name → id
        self.rows = {}               # id -> (name, age)

    def load_preset(self):
        for i, n, a in [(1, 'Ada', 24), (2, 'Bob', 31), (3, 'Cara', 19), (4, 'Dan', 27),
                        (5, 'Eve', 35), (6, 'Fay', 22), (7, 'Gus', 28)]:
            self.pk.insert_traced(i, (i, n, a))
            self.sec.insert_traced(n, i)
            self.rows[i] = (n, a)

    def next_id(self):
        return (max(self.rows) + 1) if self.rows else 1

    def next_name(self):
        used = {v[0] for v in self.rows.values()}
        for n in self.NAMES:
            if n not in used:
                return n
        return f'u{self.next_id()}'

    # ---- 工具:把引擎步骤翻译成展示步骤 ----
    @staticmethod
    def _page_label(snap, node_id):
        root = snap['root']
        leaves = []
        stack = [root]
        while stack:
            n = stack.pop()
            if n.leaf:
                leaves.append(n)
            else:
                stack.extend(n.children)
        leaves.sort(key=lambda x: x.keys[0] if x.keys else 0)
        for i, l in enumerate(leaves):
            if l.id == node_id:
                return '页' + chr(65 + i)
        return '页?'

    def _mk(self, desc, tree, engine_snap=None, base_pk=None, base_sec=None,
            hl_pk=None, hl_sec=None, conn=None, conn_hot=False):
        return {
            'desc': desc, 'tree': tree,
            'snap_pk': engine_snap if tree == 'pk' else base_pk,
            'snap_sec': engine_snap if tree == 'sec' else base_sec,
            'hl_pk': hl_pk or {}, 'hl_sec': hl_sec or {},
            'conn': conn, 'conn_hot': conn_hot,
        }

    def _locate_hl(self, s):
        ids = s['path']
        edges = {f'{a}>{b}' for a, b in zip(ids, ids[1:])}
        return {'nodes': set(ids), 'edges': edges}

    # ---- 操作:插入一行 ----
    def op_insert(self, rid, name, age):
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        out = [self._mk(f'INSERT (id={rid}, "{name}", {age}) 到达。主键 id 先定下来 —— '
                        f'它是这行数据的物理身份证,数据永远按主键组织。',
                        None, base_pk=base_pk, base_sec=base_sec)]
        row = (rid, name, age)
        for s in self.pk.insert_traced(rid, row):
            if s['phase'] == 'locate':
                out.append(self._mk(f'聚簇索引定位:按根路标 {s["root_keys"]} 逐层比较,'
                                    f'id={rid} 应进入 {self._page_label(s["snap"], s["leaf"])}。',
                                    'pk', s['snap'], base_sec=base_sec,
                                    hl_pk=self._locate_hl(s)))
            elif s['phase'] == 'update':
                out.append(self._mk(f'主键 {rid} 已存在 → 覆盖该行的值。', 'pk',
                                    s['snap'], base_sec=base_sec, hl_pk={'new': {rid}}))
            elif s['phase'] == 'write':
                sp = s['split']
                hl = {'new': {rid}}
                if sp:
                    hl['split'] = {sp['left'], sp['right']}
                    hl['up'] = {sp['sep']}
                    d = (f'叶子页已满 → 分裂为 {self._page_label(s["snap"], sp["left"])} + '
                         f'{self._page_label(s["snap"], sp["right"])},分隔键 {sp["sep"]} '
                         f'上浮到父节点当路标。行数据本体只存在聚簇索引叶子。')
                    if sp.get('root_grow'):
                        d += ' 根分裂,树长高一层!'
                else:
                    d = f'写入 (id={rid}, "{name}", {age}) 到叶子页。'
                out.append(self._mk(d, 'pk', s['snap'], base_sec=base_sec, hl_pk=hl))
        for s in self.sec.insert_traced(name, rid):
            if s['phase'] == 'locate':
                out.append(self._mk(f'二级索引定位:每个索引都要单独维护一遍,'
                                    f'同样从根向下查找 name="{name}"。',
                                    'sec', s['snap'], base_pk=base_pk,
                                    hl_sec=self._locate_hl(s)))
            elif s['phase'] == 'write':
                sp = s['split']
                hl = {'new': {name}}
                if sp:
                    hl['split'] = {sp['left'], sp['right']}
                    hl['up'] = {sp['sep']}
                    d = (f'name 树同样页满分裂,但叶子只写入 "{name}"→{rid} 一个指针 '
                         f'—— 整行数据不会被复制进来。')
                else:
                    d = f'二级索引只写入 "{name}"→{rid} 一个指针,整行数据不复制。'
                out.append(self._mk(d, 'sec', s['snap'], base_pk=base_pk, hl_sec=hl))
        self.rows[rid] = (name, age)
        return out

    # ---- 操作:按 name 查(展示回表) ----
    def op_search_name(self, name):
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        r = self.sec.search_traced(name)
        locate_hl = self._locate_hl(r)
        out = [self._mk(f'SELECT * WHERE name="{name}":name 上有二级索引 → '
                        f'优化器选择走下面的 name 树。',
                        None, base_pk=base_pk, base_sec=base_sec)]
        if not r['found']:
            out.append(self._mk(f'二级索引中没有 "{name}" —— 树查找到达叶子页但未命中,查询结束。',
                                'sec', r['snap'], base_pk=base_pk, hl_sec=locate_hl))
            return out
        rid = r['value']
        out.append(self._mk(f'定位到 {self._page_label(r["snap"], r["leaf"])},命中 "{name}"。'
                            f'注意:拿到的只有 name→主键 id={rid},叶子里没有整行数据!',
                            'sec', r['snap'], base_pk=base_pk,
                            hl_sec={**locate_hl, 'hit': {name}}))
        r2 = self.pk.search_traced(rid)
        n, a = self.rows.get(rid, ('?', '?'))
        out.append(self._mk(f'回表:拿着主键 id={rid},回到聚簇索引再查一次树 —— '
                            f'完整行数据只在这一棵树的叶子上。',
                            'pk', r2['snap'], base_sec=base_sec,
                            hl_pk=self._locate_hl(r2), conn='回表', conn_hot=True))
        out.append(self._mk(f'取出整行 (id={rid}, "{n}", {a}) 返回。全程 2 次树查找 —— '
                            f'这就是二级索引"先查目录,再取正文"的代价。',
                            'pk', r2['snap'], base_sec=base_sec,
                            hl_pk={**self._locate_hl(r2), 'hit': {rid}}, conn='回表', conn_hot=True))
        return out

    # ---- 操作:按 id 查 ----
    def op_search_id(self, rid):
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        out = [self._mk(f'主键查询 id={rid}:主键即聚簇索引,直接走这棵树,不需要回表。',
                        None, base_pk=base_pk, base_sec=base_sec)]
        r = self.pk.search_traced(rid)
        if not r['found']:
            out.append(self._mk(f'树查找到达叶子页,但没有 id={rid} —— 未命中。',
                                'pk', r['snap'], base_sec=base_sec, hl_pk=self._locate_hl(r)))
            return out
        n, a = r['value'][1], r['value'][2]
        out.append(self._mk(f'定位 {self._page_label(r["snap"], r["leaf"])},'
                            f'命中 (id={rid}, "{n}", {a}) —— 一次树查找,数据本体就在叶子。',
                            'pk', r['snap'], base_sec=base_sec,
                            hl_pk={**self._locate_hl(r), 'hit': {rid}}))
        return out

    # ---- 操作:删除一行 ----
    def op_delete(self, rid):
        if rid not in self.rows:
            return None
        name = self.rows[rid][0]
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        out = [self._mk(f'DELETE id={rid}:一个索引一个索引地删 —— 先删二级索引中的 "{name}"→{rid}。',
                        None, base_pk=base_pk, base_sec=base_sec)]
        def lab(s, which):
            # 借键/合并带修复前快照:被吸收的页在修复后已不存在,页号要用它解析
            return self._page_label(s.get('pre_snap') or s['snap'], s[which])

        phase_desc = {
            'locate': lambda s: f'二级索引定位 "{name}" → {lab(s, "leaf")}。',
            'miss': lambda s: f'二级索引中没有 "{name}"。',
            'remove': lambda s: f'从{lab(s, "leaf")}删除 "{name}"→{rid}。',
            'borrow': lambda s: (f'{lab(s, "node")} 键数低于下限 → '
                                 f'从{"左" if s["dir"] == "left" else "右"}兄弟 '
                                 f'{lab(s, "sib")} 借 1 个键保持平衡。'),
            'merge': lambda s: (f'兄弟也不够借 → {lab(s, "node")} '
                                f'与 {lab(s, "sib")} 合并成一页。'),
            'root_shrink': lambda s: '根只剩一个孩子 → 根收缩,树高 -1。',
        }
        hl_map = {
            'locate': lambda s: self._locate_hl(s),
            'miss': lambda s: self._locate_hl(s),
            'remove': lambda s: {'nodes': {s['leaf']}},
            'borrow': lambda s: {'nodes': {s['node'], s['sib']}},
            'merge': lambda s: {'nodes': {s['node'], s['sib']}},
            'root_shrink': lambda s: {},
        }
        for s in self.sec.delete_traced(name):
            out.append(self._mk(phase_desc[s['phase']](s), 'sec', s['snap'], base_pk=base_pk,
                                hl_sec=hl_map[s['phase']](s)))
        out.append(self._mk(f'二级索引删完,再删聚簇索引中的整行数据。',
                            None, base_pk=base_pk, base_sec=base_sec))
        desc2 = dict(phase_desc)
        desc2['remove'] = lambda s: f'从{lab(s, "leaf")}删除整行 (id={rid})。'
        for s in self.pk.delete_traced(rid):
            out.append(self._mk(desc2[s['phase']](s), 'pk', s['snap'], base_sec=base_sec,
                                hl_pk=hl_map[s['phase']](s)))
        del self.rows[rid]
        return out

    # ---- 操作:范围查询 ----
    def op_range(self, lo, hi):
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        r = self.pk.range_traced(lo, hi)
        out = [self._mk(f'范围查询 id ∈ [{lo}, {hi}]:先定位到起点所在的叶子页。',
                        'pk', base_pk, base_sec=base_sec, hl_pk=self._locate_hl(r))]
        names = [f'({k}, {v[0]}, {v[1]})' for k, v in r['results']]
        sample = '、'.join(names[:6]) + ('…' if len(names) > 6 else '')
        out.append(self._mk(f'沿叶子链表顺序扫过 {len(r["pages"])} 页,命中 {len(r["results"])} 行'
                            f'{(":" + sample) if names else ""} —— 范围扫描是 B+ 树的杀手锏。',
                            'pk', r['snap'], base_sec=base_sec,
                            hl_pk={'nodes': set(r['pages']), 'chain': True}))
        return out, r['results']

    # ---- 操作:随机填充 ----
    def op_random(self, k):
        base_pk, base_sec = self.pk.snap(), self.sec.snap()
        used = {v[0] for v in self.rows.values()}
        pool = [n for n in self.NAMES if n not in used]
        random.shuffle(pool)
        added = []
        for _ in range(min(k, len(pool))):
            nid = self.next_id()
            name = pool.pop()
            age = random.randint(18, 60)
            self.pk.insert_traced(nid, (nid, name, age))
            self.sec.insert_traced(name, nid)
            self.rows[nid] = (name, age)
            added.append(nid)
        desc = (f'随机插入 {len(added)} 行:id {added}。'
                f'观察叶子页如何被逐渐填满 → 触发分裂 → 键上浮。') if added else '名字池用完了。'
        return [self._mk(desc, None, self.pk.snap(), base_sec=self.sec.snap())]


# ============================================================
# 3. SVG 渲染(纯 Python 拼装,复用聊天里演示的布局算法)
# ============================================================
BLUE, GREEN, ORANGE = '#2563eb', '#16a34a', '#ea580c'
BORDER, FG, MUT, CHIP, CARD = '#d9dce3', '#1c2430', '#67707e', '#f1f3f6', '#ffffff'


def _leaves(root):
    out = []

    def w(n):
        if n.leaf:
            out.append(n)
        else:
            for c in n.children:
                w(c)
    w(root)
    return out


def _levels(root):
    lv = []

    def a(n, d):
        if d == len(lv):
            lv.append([])
        lv[d].append(n)
        if not n.leaf:
            for c in n.children:
                a(c, d + 1)
    a(root, 0)
    return lv


def _chip(x, y, w, h, label, hit=False, new=False, up=False, tip=None):
    if up:
        f, fo, s = ORANGE, .32, ORANGE
    elif new:
        f, fo, s = GREEN, .28, GREEN
    elif hit:
        f, fo, s = BLUE, .3, BLUE
    else:
        f, fo, s = CHIP, 1, 'none'
    t = f'<title>{_html.escape(tip)}</title>' if tip else ''
    return (f'<g><rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h}" rx="5" '
            f'fill="{f}" fill-opacity="{fo}" stroke="{s}" stroke-width="1.2">{t}</rect>'
            f'<text x="{x + w / 2:.0f}" y="{y + h / 2:.0f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="11" fill="{FG}">'
            f'{_html.escape(str(label))}</text></g>')


def render_tree(view, hl, kind='c', width=940):
    hl = hl or {}
    nodes = set(hl.get('nodes', ()))
    edges = set(hl.get('edges', ()))
    hit = set(hl.get('hit', ()))
    new = set(hl.get('new', ()))
    up = set(hl.get('up', ()))
    split = set(hl.get('split', ()))
    chain = hl.get('chain', False)

    root = view['root']
    leaves = _leaves(root)
    lv = _levels(root)
    n = len(leaves)
    pad, gap_x = 10, 24
    avail = (width - 2 * pad - (n - 1) * gap_x) / n
    vert = avail < 150
    if vert:
        leaf_w = int(min(96, max(64, avail)))
    else:
        leaf_w = int(min(230, max(112, avail)))
    total = leaf_w * n
    gap = (width - 2 * pad - total) / (n - 1) if n > 1 else 0
    maxm = max([len(l.keys) for l in leaves] + [1])
    leaf_h = 12 + maxm * 26 if vert else 50
    int_h, leaf_y, top = 36, 56, 8
    H = int(leaf_y + leaf_h + 28)

    cx = {}
    x = pad
    for l in leaves:
        l._x, l._w = x, leaf_w
        cx[l.id] = x + leaf_w / 2
        x += leaf_w + gap
    for d in range(len(lv) - 2, -1, -1):
        for nd in lv[d]:
            ks = [cx[c.id] for c in nd.children]
            c0 = sum(ks) / len(ks)
            nd._w = max(70, len(nd.keys) * 34 + 16)
            nd._x = c0 - nd._w / 2
            cx[nd.id] = c0

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {H}" '
         f'width="100%" height="{H}" role="img" font-family="-apple-system,Segoe UI,Roboto,sans-serif">',
         f'<defs><marker id="arr{kind}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
         f'markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUT}"/></marker></defs>']
    for d in range(len(lv) - 1):
        for pn in lv[d]:
            for c in pn.children:
                on = f'{pn.id}>{c.id}' in edges
                p.append(f'<line x1="{cx[pn.id]:.0f}" y1="{top + int_h}" x2="{cx[c.id]:.0f}" '
                         f'y2="{leaf_y}" stroke="{BLUE if on else BORDER}" '
                         f'stroke-width="{2.2 if on else 1.2}"/>')
    for d in range(len(lv) - 1):
        for pn in lv[d]:
            on = pn.id in nodes
            p.append(f'<rect x="{pn._x:.0f}" y="{top}" width="{pn._w:.0f}" height="{int_h}" rx="8" '
                     f'fill="{CARD}" stroke="{BLUE if on else BORDER}" '
                     f'stroke-width="{1.6 if on else 1.2}"/>')
            for i, k in enumerate(pn.keys):
                p.append(_chip(pn._x + 9 + i * 34, top + 6, 28, 24, k,
                               tip=f'路标键 {k}'))
    for li, l in enumerate(leaves):
        letter = chr(65 + li)
        p.append(f'<text x="{cx[l.id]:.0f}" y="{leaf_y + leaf_h + 17}" text-anchor="middle" '
                 f'font-size="11" fill="{MUT}">页{letter}</text>')
        on, sp = l.id in nodes, l.id in split
        stroke = ORANGE if sp else (BLUE if on else BORDER)
        p.append(f'<rect x="{l._x}" y="{leaf_y}" width="{l._w}" height="{leaf_h}" rx="8" '
                 f'fill="{CARD}" stroke="{stroke}" stroke-width="{1.6 if (on or sp) else 1.2}"/>')
        m = len(l.keys)
        for j, k in enumerate(l.keys):
            v = l.values[j]
            if kind == 'c':
                tip = f'主键 {k} · {v[1]} · {v[2]} 岁(整行数据就存在这一格)'
                label = f'{k} {v[1]}' if (leaf_w if not vert else min(leaf_w - 12, 150)) >= 74 else str(k)
            else:
                tip = f'{k} → 主键 {v}(目录卡:只有索引键+主键)'
                cw_est = min(leaf_w - 12, 150) if vert else (leaf_w - 12 - 2 * (m - 1)) / m
                label = f'{k}→{v}' if cw_est >= 62 else (f'{k[0]}·{v}' if cw_est >= 40 else str(v))
            if vert:
                cw = min(l._w - 12, 150)
                x0 = l._x + (l._w - cw) / 2
                y0 = leaf_y + 6 + j * 26
            else:
                cw = (l._w - 12 - 2 * (m - 1)) / m
                x0 = l._x + 6 + j * (cw + 2)
                y0 = leaf_y + 13
            p.append(_chip(x0, y0, cw, 24, label, k in hit, k in new, k in up, tip))
        if m == 0:
            p.append(f'<text x="{cx[l.id]:.0f}" y="{leaf_y + leaf_h / 2}" text-anchor="middle" '
                     f'dominant-baseline="central" font-size="11" fill="{MUT}">(空页)</text>')
        if li < n - 1:
            nxt = leaves[li + 1]
            hot = ' stroke="#2563eb" stroke-width="1.6"' if chain else f' stroke="{MUT}" stroke-width="1"'
            p.append(f'<line x1="{l._x + l._w + 1}" y1="{leaf_y + leaf_h / 2:.0f}" '
                     f'x2="{nxt._x - 1}" y2="{leaf_y + leaf_h / 2:.0f}" '
                     f'stroke-dasharray="3 3"{hot} marker-end="url(#arr{kind})"/>')
    p.append('</svg>')
    return ''.join(p), H


PAGE_CSS = '''
<style>
.bpwrap{font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;}
.phead{display:flex;justify-content:space-between;align-items:baseline;margin:10px 2px 2px;font-size:14px;font-weight:600;color:#1c2430;}
.phead .sub{font-size:12px;font-weight:400;color:#67707e;}
.conn{text-align:center;font-size:12px;color:#67707e;margin:4px 0;min-height:18px;}
.conn.hot{color:#2563eb;font-weight:600;}
.legend{font-size:12px;color:#67707e;margin-top:6px;}
.legend .sw{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:-1px;}
</style>
'''


def build_page(snap_pk, snap_sec, hl_pk=None, hl_sec=None, conn_text=None, conn_hot=False):
    s1, h1 = render_tree(snap_pk, hl_pk, 'c')
    s2, h2 = render_tree(snap_sec, hl_sec, 's')
    if conn_hot:
        conn = '<span>⬆ 回表:用主键回聚簇索引取整行</span>'
    else:
        conn = conn_text or '同一行数据:二级索引叶子只存 name→主键;完整数据只住在聚簇索引叶子页'
    legend = ('<div class="legend">'
              '<span class="sw" style="background:#2563eb"></span> 路径/命中 &nbsp;'
              '<span class="sw" style="background:#16a34a"></span> 新写入 &nbsp;'
              '<span class="sw" style="background:#ea580c"></span> 分裂/上浮 &nbsp;'
              '· 内部节点 = 路标(只存键) · 叶子 = 数据页 · 页间虚线 = 叶子链表</div>')
    doc = (PAGE_CSS + '<div class="bpwrap">'
           + '<div class="phead"><span>聚簇索引 · 主键树</span>'
             '<span class="sub">叶子页 = 整行数据(数据本体)</span></div>'
           + s1
           + f'<div class="conn{" hot" if conn_hot else ""}">{conn}</div>'
           + '<div class="phead"><span>二级索引 · name 树</span>'
             '<span class="sub">叶子页 = name → 主键(目录卡)</span></div>'
           + s2 + legend + '</div>')
    return doc, h1 + h2 + 90


# ============================================================
# 4. Streamlit UI
# ============================================================
st.set_page_config(page_title='B+ 树可视化 · bptree_visualizer',
                   page_icon='🌳', layout='wide')

st.markdown('''<style>
.hero{background:linear-gradient(135deg,#2563eb 0%,#7c3aed 100%);color:#fff;
padding:16px 24px;border-radius:14px;font-size:22px;font-weight:600;margin-bottom:8px;}
.stepdesc{background:#eef2ff;border-left:4px solid #2563eb;padding:10px 14px;
border-radius:8px;font-size:15px;color:#1c2430;min-height:48px;}
.block-container{padding-top:1.4rem;}
</style>''', unsafe_allow_html=True)
st.markdown('<div class="hero">🌳 B+ 树可视化 —— 一条数据在数据库索引里的一生</div>',
            unsafe_allow_html=True)


def new_demo(order):
    d = Demo(order)
    d.load_preset()
    return d


if 'order' not in st.session_state:
    st.session_state.order = 4
if 'demo' not in st.session_state:
    st.session_state.demo = new_demo(st.session_state.order)
for k, v in [('steps', []), ('idx', 0), ('play', False), ('results', None), ('history', [])]:
    st.session_state.setdefault(k, v)

demo: Demo = st.session_state.demo

# ---------------- 侧边栏:操作面板 ----------------
sb = st.sidebar
sb.markdown('### 🎛 操作面板')
order = sb.select_slider('阶数(每页最多键数)', options=[3, 4, 5, 6],
                         value=st.session_state.order)
if order != st.session_state.order:
    st.session_state.order = order
    st.session_state.demo = new_demo(order)
    st.session_state.steps, st.session_state.idx = [], 0
    st.session_state.play, st.session_state.results = False, None
    st.rerun()

sb.divider()
with sb.expander('🌱 插入一行'):
    ins_id = st.number_input('主键 id', 1, 99999, value=demo.next_id(), key='ins_id')
    ins_name = st.text_input('name(二级索引键,不可重复)', value=demo.next_name(), key='ins_name')
    ins_age = st.number_input('age', 1, 120, 25, key='ins_age')
    if st.button('插入', key='do_insert', type='primary'):
        if ins_id in demo.rows:
            sb.warning(f'id={ins_id} 已存在,换一个。')
        elif not ins_name.strip():
            sb.warning('name 不能为空。')
        elif any(v[0] == ins_name.strip() for v in demo.rows.values()):
            sb.warning(f'name "{ins_name}" 已存在(二级索引键要求唯一)。')
        else:
            st.session_state.steps = demo.op_insert(int(ins_id), ins_name.strip(), int(ins_age))
            st.session_state.idx = 0
            st.session_state.play = False
            st.session_state.results = None
            st.session_state.history.append(f'🌱 插入 (id={int(ins_id)}, "{ins_name.strip()}", {int(ins_age)})')

with sb.expander('🗑 删除一行'):
    del_id = st.number_input('要删除的主键 id', 1, 99999, value=1, key='del_id')
    if st.button('删除', key='do_delete'):
        if int(del_id) not in demo.rows:
            sb.warning(f'id={int(del_id)} 不存在。')
        else:
            st.session_state.steps = demo.op_delete(int(del_id))
            st.session_state.idx = 0
            st.session_state.play = False
            st.session_state.results = None
            st.session_state.history.append(f'🗑 删除 id={int(del_id)}')

with sb.expander('🔍 查找'):
    mode = st.radio('按什么查', ['主键 id(1 次树查找)', 'name(2 次:二级索引 + 回表)'],
                    key='q_mode', label_visibility='collapsed')
    if mode.startswith('主键'):
        q_id = st.number_input('id', 1, 99999, value=5, key='q_id')
        if st.button('查找', key='do_q1'):
            st.session_state.steps = demo.op_search_id(int(q_id))
            st.session_state.idx, st.session_state.play = 0, False
            r = demo.pk.search_traced(int(q_id))
            v = r['value']
            st.session_state.results = ([{'主键': int(q_id), '姓名': v[1], '年龄': v[2]}]
                                        if r['found'] else [])
            st.session_state.history.append(f'🔍 查 id={int(q_id)}')
    else:
        q_name = st.text_input('name', value='Eve', key='q_name')
        if st.button('查找', key='do_q2'):
            st.session_state.steps = demo.op_search_name(q_name.strip())
            st.session_state.idx, st.session_state.play = 0, False
            st.session_state.results = None
            st.session_state.history.append(f'🔍 查 name="{q_name.strip()}"(回表演示)')

with sb.expander('📏 范围查询(叶子链表扫描)'):
    lo = st.number_input('从 id', 1, 99999, value=2, key='r_lo')
    hi = st.number_input('到 id', 1, 99999, value=6, key='r_hi')
    if st.button('范围查询', key='do_range'):
        if lo > hi:
            sb.warning('起点不能大于终点。')
        else:
            st.session_state.steps, st.session_state.results = demo.op_range(int(lo), int(hi))
            res = st.session_state.results
            st.session_state.results = [{'主键': k, '姓名': v[0], '年龄': v[1]} for k, v in res]
            st.session_state.idx, st.session_state.play = 0, False
            st.session_state.history.append(f'📏 范围 [{int(lo)}, {int(hi)}]')

sb.divider()
c_a, c_b = sb.columns(2)
if c_a.button('🎲 随机填充', key='do_rand'):
    st.session_state.steps = demo.op_random(6)
    st.session_state.idx, st.session_state.play, st.session_state.results = 0, False, None
    st.session_state.history.append('🎲 随机插入 6 行')
if c_b.button('♻️ 重置', key='do_reset'):
    st.session_state.demo = new_demo(st.session_state.order)
    st.session_state.steps, st.session_state.idx = [], 0
    st.session_state.play, st.session_state.results = False, None
    st.session_state.history.append('♻️ 重置')

# ---------------- 主区:步骤回放 ----------------
steps = st.session_state.steps
idx = st.session_state.idx
demo = st.session_state.demo

if steps:
    st.markdown(f'<div class="stepdesc">{steps[idx]["desc"]}</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2.4])
    if c1.button('⬅ 上一', disabled=idx == 0, key='prev'):
        st.session_state.idx -= 1
        st.session_state.play = False
        st.rerun()
    if c2.button('➡ 下一', disabled=idx >= len(steps) - 1, key='next'):
        st.session_state.idx += 1
        st.rerun()
    if c3.button('⏸ 暂停' if st.session_state.play else '▶ 播放', key='play_btn'):
        st.session_state.play = not st.session_state.play
        st.rerun()
    st.caption(f'步骤 {idx + 1} / {len(steps)}')
    if st.session_state.play and idx < len(steps) - 1:
        time.sleep(0.9)
        st.session_state.idx = idx + 1
        if idx + 1 >= len(steps) - 1:
            st.session_state.play = False
        st.rerun()
else:
    st.info('👈 在左侧操作:插入 / 删除 / 查找 / 范围查询。每步都能看到 B+ 树如何定位、分裂、回表。')

cur = steps[idx] if steps else None
snap_pk = cur['snap_pk'] if cur else demo.pk.snap()
snap_sec = cur['snap_sec'] if cur else demo.sec.snap()
doc, h = build_page(snap_pk, snap_sec,
                    cur['hl_pk'] if cur else None,
                    cur['hl_sec'] if cur else None,
                    cur['conn'] if cur else None,
                    bool(cur['conn_hot']) if cur else False)
components.html(doc, height=h, scrolling=False)

# ---------------- 统计 + 结果 + 说明 ----------------
m1, m2, m3, m4 = st.columns(4)
leaves = _leaves(demo.pk.root)
m1.metric('数据行数', len(demo.rows))
m2.metric('聚簇索引叶子页', len(leaves))
m3.metric('树高', len(_levels(demo.pk.root)))
m4.metric('阶数(每页最多键数)', demo.M)

if st.session_state.results:
    st.dataframe(st.session_state.results, use_container_width=True, hide_index=True)

with st.expander('📖 原理速览:为什么数据库都爱 B+ 树'):
    st.markdown('''
- **索引 ≠ 数据**:整行数据只存在**聚簇索引(主键树)**的叶子页里;二级索引只是一张"目录卡",叶子上只有 `索引键 → 主键` 两个小字段。
- **查找 = 树下降**:从根开始,内部节点只放"路标键"(子树最小键的副本),每层做一次比较,O(log n) 次比较直达叶子。
- **插入可能分裂**:叶子页满(键数 > 阶数)→ 一分为二,分隔键**复制**上浮当路标;父节点也满就继续分裂,根分裂则树长高一层 —— 所有的叶子永远在同一层。
- **删除可能借键/合并**:删到低于下限就向兄弟借 1 个键,兄弟也不够就合并,父节点连锁收缩,极端时树高 -1。
- **回表**:走二级索引只拿到主键,必须再查一次聚簇索引取整行 —— 所以有"索引覆盖"和"最左前缀"这些优化话题。
- **范围查询强**:叶子页用链表串起来,定位到起点后顺序扫描即可,不需要再回到上层。
- **对应 InnoDB**:这里的"页"≈ InnoDB 的 16KB 页,聚簇索引 ≈ InnoDB 主键,二级索引 ≈ InnoDB 普通索引;真实引擎还有 Buffer Pool 和 redo log(WAL)。
    ''')

st.caption('单文件 Streamlit 应用,结构对标 [cnn_visualizer](https://github.com/fumolan/cnn_visualizer) '
           '· Python 负责引擎与渲染,浏览器只负责显示')
