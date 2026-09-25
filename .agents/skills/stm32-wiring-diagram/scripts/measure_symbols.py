#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
符号尺寸标定工具 —— wirelib._needs() 里的数字就是这么来的。

用法:
    python measure_symbols.py            # 打印各符号真实外轮廓
    python measure_symbols.py --check    # 与 _needs() 的值对比, 不一致就报错

为什么要这个: `_needs()` 给出每个符号的包围盒, verify() 靠它查
"器件画出画布" 和 "器件互相重叠"。这些数字必须和实际绘制几何一致 ——
估大了, 相邻支路会整片误报重叠; 估小了, 画出画布的器件会漏检。
改了符号的几何(比如加个标签、把箭头画长一点)之后, 跑一次 --check
就能知道 _needs() 是否要跟着改。
"""
import argparse
import os
import re
import sys

# 把符号画在 (400,400), 量出相对中心的极值
PROBES = [
    ("led",          lambda w: w.led(400, 400, label="LED1")),
    ("resistor",     lambda w: w.resistor(400, 400, label="1K")),
    ("npn",          lambda w: w.npn(400, 400, label="Q1")[0]),
    ("push_button",  lambda w: w.push_button(400, 400, label="KEY")[0]),
    ("ground",       lambda w: w.ground(400, 400)),
    ("vcc",          lambda w: w.vcc(400, 400, "3V3")),
    ("power_in",     lambda w: w.power_in(400, 400, "+5V")),
    ("crystal",      lambda w: w.crystal(400, 400, label="8MHz")[0]),
    ("capacitor",    lambda w: w.capacitor(400, 400, label="100nF")),
    ("rgb_led",      lambda w: w.rgb_led(400, 400, label="RGB")[0]),
    ("junction",     lambda w: w.junction(400, 400)),
    ("swd_header",   lambda w: w.swd_header(400, 400, 110, 90)[0]),
]

# _needs() 用的关键字(要和实际调用时一致, 否则算出来的框对不上)
KW = {
    "led": {"s": 13, "label": "LED1"},
    "resistor": {"w": 42, "h": 15, "label": "1K"},
    "npn": {"s": 17, "label": "Q1"},
    "push_button": {"w": 44, "h": 30, "label": "KEY"},
    "ground": {"size": 13},
    "vcc": {"label": "3V3"},
    "power_in": {"label": "+5V"},
    "crystal": {"w": 30, "h": 15, "label": "8MHz"},
    "capacitor": {"gap": 7, "plate": 15, "label": "100nF"},
    "rgb_led": {"s": 13, "label": "RGB"},
    "junction": {},
    "swd_header": {"w": 110, "h": 90},
}


def measure(svg, cx=400.0, cy=400.0):
    """量出 SVG 里所有图元的极值, 转成相对 (cx, cy) 的偏移。"""
    xs, ys = [], []
    pats = [
        (r'<line [^>]*x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="([\d.-]+)"',
         lambda m: ([m.group(1), m.group(3)], [m.group(2), m.group(4)])),
        (r'<rect [^>]*x="([\d.-]+)" y="([\d.-]+)" width="([\d.-]+)" height="([\d.-]+)"',
         lambda m: ([m.group(1), float(m.group(1)) + float(m.group(3))],
                    [m.group(2), float(m.group(2)) + float(m.group(4))])),
        (r'<circle [^>]*cx="([\d.-]+)" cy="([\d.-]+)" r="([\d.-]+)"',
         lambda m: ([float(m.group(1)) - float(m.group(3)),
                     float(m.group(1)) + float(m.group(3))],
                    [float(m.group(2)) - float(m.group(3)),
                     float(m.group(2)) + float(m.group(3))])),
    ]
    for pat, get in pats:
        for m in re.finditer(pat, svg):
            a, b = get(m)
            xs += [float(v) for v in a]
            ys += [float(v) for v in b]
    for m in re.finditer(r'<polygon points="([^"]+)"', svg):
        for pair in m.group(1).split():
            px, py = pair.split(",")
            xs.append(float(px))
            ys.append(float(py))
    for m in re.finditer(r'<text x="([\d.-]+)" y="([\d.-]+)"[^>]*font-size="([\d.]+)"'
                         r'[^>]*text-anchor="(\w+)"[^>]*>([^<]*)<', svg):
        x, y, sz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        anc, t = m.group(4), m.group(5)
        wid = sum(sz * (1.0 if ord(c) > 0x2E80 else 0.55) for c in t)
        x0 = x if anc == "start" else (x - wid if anc == "end" else x - wid / 2)
        xs += [x0, x0 + wid]
        ys += [y - sz * 0.72, y + sz * 0.18]
    if not xs:
        return None
    return (min(xs) - cx, min(ys) - cy, max(xs) - cx, max(ys) - cy)


def find_wirelib():
    """逐级向上找含 wirelib.py 的目录（可用环境变量 WIRELIB_DIR 覆盖）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _paths import find_root
    return find_root()


def main():
    ap = argparse.ArgumentParser(description="wirelib 符号尺寸标定")
    ap.add_argument("--check", action="store_true",
                    help="与 _needs() 对比, 不一致则退出码 1")
    args = ap.parse_args()

    root = find_wirelib()
    if not root:
        print("错误: 找不到 wirelib.py", file=sys.stderr)
        return 2
    sys.path.insert(0, root)
    import wirelib as w

    bad = 0
    for name, fn in PROBES:
        real = measure(fn(w))
        if real is None:
            print(f"{name:13s} 量不到图元")
            continue
        need = w._needs(name, **KW.get(name, {}))
        real_s = "(%7.1f, %7.1f, %7.1f, %7.1f)" % real
        if not args.check:
            need_s = ("(%7.1f, %7.1f, %7.1f, %7.1f)" % need) if need else "None"
            print(f"{name:13s} 实测 {real_s}   _needs {need_s}")
            continue
        # _needs 必须完整包含实测轮廓(可略大, 不可小)
        if need is None:
            print(f"[缺] {name:13s} _needs() 没有这个符号")
            bad += 1
            continue
        if (need[0] > real[0] + 0.5 or need[1] > real[1] + 0.5 or
                need[2] < real[2] - 0.5 or need[3] < real[3] - 0.5):
            print(f"[小] {name:13s} 实测 {real_s} 超出 _needs "
                  "(%7.1f, %7.1f, %7.1f, %7.1f) —— 会漏检" % need)
            bad += 1
        else:
            slack = (need[0] - real[0], need[1] - real[1],
                     real[2] - need[2], real[3] - need[3])
            print(f"[ok] {name:13s} 余量 左{slack[0]:5.1f} 上{slack[1]:5.1f} "
                  f"右{slack[2]:5.1f} 下{slack[3]:5.1f}")

    if args.check:
        print()
        if bad:
            print(f"_needs() 需要修正的地方: {bad} 处")
            return 1
        print("全部符号的 _needs() 都完整覆盖实测轮廓。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
