#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网表连通性体检 —— 电路**对不对**，与 check_svg.py（排版**好不好看**）互补。

用法:
    python check_net.py <svg文件> [更多svg...]
    python check_net.py 工程目录/*.svg

退出码: 0 = 电气上没查出问题, 1 = 有 / 2 = 用法或环境错误。

它查**八类**电气错误 —— **这些 check_svg.py 全都查不出，肉眼也看不出**：

  1. 短路        VCC 与 GND 落在同一张网
  2. 旁路        元件两端接在同一张网（用它等于没用它）
  3. 穿体        导线纵穿元件本体 —— 竖放的电阻/电容没有内置引线,
                 引线从本体上方一路画到下方就是从元件身上穿过去了
  4. 悬空        元件端子没接到任何导线（差几像素没接上, 图上完全看不出来）
  5. 接错        自绘元件声明了"该接在哪"（declare(expect=...)）但没兑现 ——
                 接错节点时端子照样"接上了", 前四类都不会报, 只有这条能抓
  6. 畸形        坐标不是数字的 <line>, 会被解析器静默丢弃。单独列出来是因为
                 它的连锁反应(一片悬空/旁路)最容易把真病因埋掉
  7. 飘端子      自绘符号声明的端子**离画出来的图形太远**（悬在图形外的
                 空白处, 或图形内部的空洞里）——
                 declare(terminals=...) 是作者手填的坐标, 与符号内部的绘制
                 代码之间没有一致性约束(内置符号有 measure_symbols.py 校准,
                 自绘符号没有)。端子悬在空白处 17px, 导线**确实**接上了,
                 连通性完美, 但图上看着像"这个元件没接线"。
  8. 孤标签      网络标签 marker() 落了单 —— 同号标签才相连, 只有一个
                 等于什么都没连(编号写错? 或另一端忘了画?)。

为什么必须有这个工具: 短路和"元件被旁路"在图上**就是一根普通的直线**,
线条笔直、元件规整、不压字不重叠。排版检查给满分, 人眼也给满分。
只有把图还原成网表、做连通性分析, 才能发现它其实是错的。

连通规则（决定成败, 别改）: **端点相接才算连接; 中途交叉不算** ——
除非交点处有 junction 圆点。少了这条, 两条只是视觉上交叉的导线会被判成
连通, 于是报出一堆"分压网络短路"的假阳性。
"""
import argparse
import glob
import os
import sys


def find_wirelib():
    """逐级向上找含 wirelib.py 的目录（可用环境变量 WIRELIB_DIR 覆盖）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _paths import find_root
    return find_root()


def main():
    ap = argparse.ArgumentParser(description="SVG 电路网表连通性体检")
    ap.add_argument("files", nargs="+", help="SVG 文件路径 (支持通配符)")
    ap.add_argument("--show-nets", action="store_true",
                    help="额外打印每张网的成员, 便于核对功能网是否正确")
    ap.add_argument("--dangling-tol", type=float, default=None,
                    help="悬空端子的容差(px)。默认任意距离都报, 只是按距离排序")
    args = ap.parse_args()

    root = find_wirelib()
    if not root:
        print("错误: 找不到 wirelib.py", file=sys.stderr)
        return 2
    sys.path.insert(0, root)
    from wirelib import analyze

    paths = []
    for pat in args.files:
        got = glob.glob(pat)
        paths.extend(got if got else [pat])

    total = 0
    for p in sorted(paths):
        if not os.path.exists(p):
            print(f"跳过(不存在): {p}")
            continue
        r = analyze(p, quiet=True)
        # 每个文件打印一个紧凑的结论
        print(f"== {p}: {r['n_lines']} 条导线, {r['n_dots']} 个结点, "
              f"{len(r['components'])} 个元件 ==")
        n = 0
        if r.get("malformed_lines"):
            bl = r["malformed_lines"]
            print(f"  [畸形] {len(bl)} 条 <line> 的坐标不是数字, 已被静默丢弃。")
            print(f"         这通常是变量遮蔽造成的 —— 比如把颜色常量 WIRE")
            print(f"         当成了坐标。下面的问题多半是它的连锁反应, 先修这个。")
            for b in bl[:3]:
                print(f"           {b}")
            n += len(bl)
        if r["vcc_gnd_shorted"]:
            print("  [短路] VCC 与 GND 落在同一张网！电路一上电就烧。")
            n += 1
        for base, net, hint in r["bypassed"]:
            print(f"  [旁路] {base} 两端接在同一张网 —— 该元件形同不存在{hint}")
            n += 1
        for base, pt, hint in r["crossed_bodies"]:
            print(f"  [穿体] 导线纵穿 {base} 本体 @ ({pt[0]:.0f},{pt[1]:.0f}) "
                  f"—— 该元件被旁路{hint}")
            n += 1
        for nm, pt, dd, near, hint in sorted(r["dangling"],
                                             key=lambda x: -(x[2] or 0)):
            if args.dangling_tol is not None and (dd or 0) > args.dangling_tol:
                continue
            extra = "" if dd is None else f"（差 {dd:.1f}px）"
            print(f"  [悬空] {nm} @ ({pt[0]:.0f},{pt[1]:.0f}) 没接到任何导线{extra}{hint}")
            n += 1
        for nm, want, actual, why in r.get("miswired", []):
            if actual is None:
                print(f"  [接错] {nm} 声明应与 {want} 同网, 但 {why}")
            else:
                print(f"  [接错] {nm} 声明应与 {want} 同网, 实际却在 {actual}")
            n += 1
        for name, tn, pt, dd, ext in r.get("stray_terms", []):
            print(f"  [飘端子] {name}.{tn} @ ({pt[0]:.0f},{pt[1]:.0f}) 离开本符号"
                  f"画出的图形 {dd:.1f}px")
            print(f"           → 该端子在 ({ext[0]:.0f}..{ext[2]:.0f}, "
                  f"{ext[1]:.0f}..{ext[3]:.0f}) 的图形之外。导线接在这个点上, "
                  f"但旁边没有图形 ——")
            print(f"             图上看着像没接线。改 declare(terminals=...) 里的坐标, "
                  f"或修符号的绘制代码。")
            n += 1
        for tag in r.get("lonely_tags", []):
            print(f"  [孤标签] 网络标签「{tag}」只出现一次 —— 同号标签才相连, "
                  f"只有一个等于什么都没连。")
            print(f"           → 检查编号是否写错（① 对 ②？）, 或另一端忘了画。")
            n += 1
        if args.show_nets:
            for i, (root_, ms) in enumerate(sorted(r["nets"].items(),
                                                   key=lambda kv: -len(kv[1])), 1):
                if len(ms) >= 2:
                    print(f"    网{i}: {ms}")
        if n == 0:
            print("  电气连通性: 无短路 / 无旁路 / 无穿体 / 无悬空端子 / "
                  "无接错 / 无畸形线段 / 无飘端子 / 无孤标签")
        total += n
        print()

    print(f"===== 合计电气问题数: {total} =====")
    if total:
        print("必须修掉才能交付。常见改法见 SKILL.md 的「电气陷阱」一节。")
    else:
        print("电气连通性干净。注意: 这只证明「连对了」, 不证明参数选得对 ——")
        print("静态工作点、增益、电容取值仍需自己核对。")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
