#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定位 `wirelib.py` —— 所有 skill 脚本共用这一处逻辑。

为什么要单独一个模块: 早先这段 5 个脚本各抄了一份, 而且都带一个写死的
`D:/SCM` 兜底。别人 clone 下去之后那个路径不存在, 脚本会报"找不到
wirelib.py", 而真正的原因只是"路径写死了"。

查找顺序(先找到先用):
  1. 环境变量 `WIRELIB_DIR` —— 显式指定, 优先
  2. 从本文件所在目录**逐级向上**找 wirelib.py —— 覆盖
     `<仓库>/.agents/skills/<技能>/scripts/` 这种标准位置,
     也覆盖把 skill 放到别的深度的情况
  3. 当前工作目录 (CI / 在仓库根直接跑的场合)
"""
import os
import sys

_CACHE = []


def find_root():
    """返回含 wirelib.py 的目录; 找不到返回 None。"""
    if _CACHE:
        return _CACHE[0]

    cands = []
    env = os.environ.get("WIRELIB_DIR")
    if env:
        cands.append(env)

    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(8):                    # 最多上溯 8 层, 够深了
        cands.append(d)
        parent = os.path.dirname(d)
        if parent == d:                   # 到盘根了
            break
        d = parent

    cands.append(os.getcwd())

    for c in cands:
        if c and os.path.exists(os.path.join(c, "wirelib.py")):
            _CACHE.append(c)
            return c
    return None


def add_to_path():
    """把 wirelib 所在目录加进 sys.path。找不到时返回 None(调用方自行报错)。"""
    root = find_root()
    if root and root not in sys.path:
        sys.path.insert(0, root)
    return root


def fail_hint():
    """找不到 wirelib.py 时给调用方的可执行提示。"""
    return (
        "错误: 找不到 wirelib.py。\n"
        "  · 本技能的图依赖仓库根目录的 wirelib.py; 请确认它在仓库里。\n"
        "  · 或设环境变量显式指定: WIRELIB_DIR=/path/to/dir-with-wirelib\n"
        "  · 本脚本会从自身位置逐级向上找, 也会看当前工作目录。"
    )
