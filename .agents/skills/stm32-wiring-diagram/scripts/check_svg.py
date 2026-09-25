#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
接线图体检工具 —— 生成后跑一次, 确认排版没问题。

用法:
    python check_svg.py <svg文件> [更多svh...]
    python check_svg.py 工程目录/*.svg

退出码: 0 = 全部干净, 1 = 有问题。

它做两件事:
  1. 调 wirelib.verify() 查排版问题 (文字重叠 / 文字压线 / 平行线过近)
  2. 可选地渲染一张 PNG (--png), 方便用眼睛再确认一次

为什么要单独一个工具: 让 agent 在交付前有一个"必过的门"。
verify() 是纯文本分析, 不会漏掉只差几像素的重叠; PNG 是给人看的补充。
两者都过才算完成。
"""
import os
import sys
import argparse
import glob


def main():
    ap = argparse.ArgumentParser(description="SVG 接线图排版体检")
    ap.add_argument("files", nargs="+", help="SVG 文件路径 (支持通配符)")
    ap.add_argument("--png", action="store_true", help="同时渲染 PNG 便于肉眼确认")
    ap.add_argument("--min-gap", type=int, default=18,
                    help="水平导线最小安全间距, 默认 18")
    args = ap.parse_args()

    # 找到 wirelib（逐级向上找，可用 WIRELIB_DIR 覆盖）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _paths import add_to_path, fail_hint
    if not add_to_path():
        print(fail_hint(), file=sys.stderr)
        return 2

    from wirelib import verify

    paths = []
    for pat in args.files:
        got = glob.glob(pat)
        paths.extend(got if got else [pat])

    total = 0
    for p in sorted(paths):
        if not os.path.exists(p):
            print(f"跳过(不存在): {p}")
            continue
        n = verify(p, min_h_gap=args.min_gap)
        print()
        total += n

    if args.png:
        try:
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
        except ImportError:
            print("(未安装 svglib/reportlab, 跳过 PNG 渲染)")
        else:
            for p in sorted(paths):
                if not os.path.exists(p):
                    continue
                out = os.path.splitext(p)[0] + "_check.png"
                renderPM.drawToFile(svg2rlg(p), out, fmt="PNG")
                print(f"已渲染: {out}   (中文会显示为方块, 属渲染器限制, 不影响 SVG)")
            print()

    print(f"===== 合计问题数: {total} =====")
    if total:
        print("必须修掉才能交付。常见改法见 SKILL.md 的「排版经验」。")
    else:
        print("排版干净, 可以交付。")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
