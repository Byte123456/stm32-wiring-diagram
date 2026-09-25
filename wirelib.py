# -*- coding: utf-8 -*-
"""
接线示意图绘制库 (wirelib)
================================================================
给 STM32 实验工程生成"看得懂就能接"的接线示意图, 输出 SVG。

设计目标:
  1. 器件符号库  —— LED / 电阻 / 按键 / 三极管 / 地 / 电源 / 灯珠 ...
  2. 数据驱动    —— 描述"引脚 -> 器件 -> 连接", 自动排版, 不手写坐标
  3. 电路模板    —— 常用接法(三极管驱动、共阳/共阴、按键等)封装成块

坐标系统: SVG 左上角为原点, y 向下。所有长度单位 = 像素。

用法见 .agents/skills/stm32-wiring-diagram/SKILL.md 与 references/quickref.md。
"""

import math

# ============================ 全局样式 ============================
W, H = 1180, 820                       # 默认画布 (可被 doc() 覆盖)
BG, FG, DIM = "#ffffff", "#1a1a1a", "#666666"
WIRE = "#37474f"                       # 导线
LEDC = "#e53935"                       # LED / 二极管 (红)
RESC = "#1e88e5"                       # 电阻 (蓝)
GNDC = "#37474f"                       # 地 (深灰)
VC = "#c62828"                         # 电源 (红)
NPB = "#6a1b9a"                        # 三极管 (紫)
NOTE_BG, NOTE_BR = "#e3f2fd", "#1e88e5"   # 说明框 (蓝)
WARN_BG, WARN_BR = "#fff8e1", "#ffb300"   # 警告框 (黄)
OK_BG, OK_BR = "#e8f5e9", "#43a047"       # 特点框 (绿)
FONT = "Microsoft YaHei, Segoe UI, sans-serif"


# ============================ 排版元数据 ============================
# 装饰性图元(底框、分隔线、说明框)不该参与"导线/器件重叠"检查, 也不该
# 参与边界检查(底框本来就要贴边)。做法是给它打一个 data-* 标记,
# 由 _segments() / _boxes() / verify() 过滤掉。
DECO = ' data-deco="1"'

# 每个画图函数都注册自己的外接矩形, 供 verify() 检查"器件是否超出画布"。
# 用 dict 而不用具名元组: 便于后续加 kind / name 之类的字段。
BOX = {}


def _reg(kind, x0, y0, x1, y1, name=None):
    """登记一个器件/图元组的包围盒。返回 box 本身, 便于调用方串联。"""
    b = {"kind": kind, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "name": name}
    return b


# ============================ 基础图元 ============================
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, anchor="start", color=FG, weight="normal", family=FONT):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{esc(s)}</text>')


def line(x1, y1, x2, y2, color=WIRE, w=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="{w}"{d}/>')


def rect(x, y, w, h, fill="none", stroke=FG, sw=1.5, rx=0):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>')


def circle(cx, cy, r, fill="none", stroke=FG, sw=1.5):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def polygon(points, fill, stroke=None, sw=1):
    st = stroke or fill
    pts = " ".join(f"{x},{y}" for x, y in points)
    return f'<polygon points="{pts}" fill="{fill}" stroke="{st}" stroke-width="{sw}"/>'


def junction(cx, cy, r=3.5, color=WIRE):
    """导线连接点(实心圆)."""
    return circle(cx, cy, r, fill=color, stroke=color)


def marker(x, y, num, r=13):
    """
    网络标签节点: 圆圈 + 编号, 用来代替"拉长导线穿过整张图"。
    **相同编号的节点在电气上是同一张网** —— `analyze()` 会把它们并起来
    (带 `data-net` 标记, 由 `_net_markers()` 提取)。
    带 data-node 标记, 排版自检器会跳过它们 —— 它们故意画在导线端点,
    不该算"文字压线"。
    """
    return (f'<circle data-node="1" data-net="{esc(str(num))}" cx="{x}" cy="{y}" r="{r}" '
            f'fill="#ffffff" stroke="{WIRE}" stroke-width="2"/>'
            f'<text data-node="1" x="{x}" y="{y + 5}" font-family="{FONT}" '
            f'font-size="13" fill="{FG}" font-weight="bold" '
            f'text-anchor="middle">{esc(str(num))}</text>')


def _net_markers(svg_text):
    """提取所有 marker() 网络标签: [(编号, (x, y)), ...]。

    编号是字符串(调用方可能写 1 也可能写 "A"), 所以按字符串比较。
    """
    import re
    out = []
    for m in re.finditer(r'<circle\s+data-node="1"\s+data-net="([^"]*)"\s+'
                         r'cx="([\d.-]+)"\s+cy="([\d.-]+)"', svg_text):
        out.append((m.group(1), (float(m.group(2)), float(m.group(3)))))
    return out


def _needs(sym, **kw):
    """
    推算符号的包围盒 —— 让 Doc.add() 能在调用方没写 bounds 时自动补上。

    数值不是估的, 是用 _measure_symbols.py 量出来的真实外轮廓:
    把符号画在原点附近渲染一次, 取所有 line/rect/circle/polygon/text 的
    极值。**带标签** 的尺寸(标签会往上占约 15px)。

    别凭感觉调这些数字: 多算几像素会让相邻支路误报"器件重叠"
    (行间距 60px 的一排电阻, 早先估成 62px 就整片误报);
    少算几像素则会让真正画到画布外的器件漏检。
    """
    s = kw.get("s", 13)
    lab = 15 if kw.get("label") else 0        # 标签向上的额外高度
    if sym == "led":
        return (-s, -s - lab - 6, s, s + 21 + (0 if not kw.get("label") else 1))
    if sym == "resistor":
        w, h = kw.get("w", 42), kw.get("h", 15)
        if kw.get("vertical"):
            # 竖放: 标签在右侧
            return (-h / 2, -w / 2, h / 2 + (28 if kw.get("label") else 0), w / 2)
        return (-w / 2, -h / 2 - lab - 1, w / 2, h / 2)
    if sym == "npn":
        return (-s, -s - lab - 3, s, s)
    if sym == "push_button":
        w, h = kw.get("w", 44), kw.get("h", 30)
        # 标签基线在 cy - h/2 - 20, 字号 12.5 -> 顶端再上 9px
        return (-w / 2 - 4, -h / 2 - (29 if kw.get("label") else 0), w / 2 + 4, h / 2)
    if sym == "ground":
        z = kw.get("size", 13)
        return (-z / 2, 0, z / 2, z * 0.5 + z * 1.34 + (13 if kw.get("label") else 0))
    if sym == "vcc":
        return (-10, -34, 10, 0)
    if sym == "power_in":
        return (-35, -9, 26, 9)
    if sym == "crystal":
        w, h = kw.get("w", 30), kw.get("h", 15)
        return (-w / 2 - 2, -h - 1, w / 2 + 2, h + (23 if kw.get("label") else 0) + 1)
    if sym == "capacitor":
        gap, plate = kw.get("gap", 7), kw.get("plate", 15)
        if kw.get("vertical"):
            return (-plate, -gap - 12, plate + (37 if kw.get("label") else 0), gap + 12)
        return (-gap - 12, -plate - (16 if kw.get("label") else 0), gap + 12, plate)
    if sym == "rgb_led":
        return (-s - 22, -s - 8, s + 48, s + 28)
    if sym == "junction":
        return (-4, -4, 4, 4)
    if sym == "mcu_block":
        # 以左上角 (x, y) 为参照。包围盒必须**跟着引脚表走** ——
        # 引脚引线向左右各伸 20px, 引线上方还有一行引脚名(基线 dy-7,
        # 字号 12 -> 顶端再上约 9px, 即 dy-16)。
        # 早先这里无条件返回 (0, 0, w+20, h+8), 只有"引线宽度"没有标签余量:
        # 左右都挂引脚名的 MCU, 最外侧那个标签会落在登记框外, 于是排版门
        # 可能漏掉一个真被画布裁掉的 MCU。所以下面按实际引脚算出来。
        w, h = kw.get("w", 190), kw.get("h", 260)
        x0, y0, x1, y1 = 0.0, 0.0, float(w), float(h)
        if kw.get("show_pin_names", True):
            lab_up = 16            # 引脚名顶端相对引线的上方高度
            if kw.get("label_above", True):
                # 标签居中在引线中点, 宽度最多 W_LAB; 方框通常够宽,
                # 但窄方框 + 长引脚名时仍可能探出, 所以按一半宽度兜底。
                W_LAB = 34
                for name, dy in kw.get("pins_right") or ():
                    x1 = max(x1, w + 20 + W_LAB / 2)
                    y0 = min(y0, dy - lab_up)
                    y1 = max(y1, dy)
                for name, dy in kw.get("pins_left") or ():
                    x0 = min(x0, -20 - W_LAB / 2)
                    y0 = min(y0, dy - lab_up)
                    y1 = max(y1, dy)
            else:
                # 标签画在引线右侧(右) / 左侧(左), 按 6px 间距 + 文本宽度估
                for name, dy in kw.get("pins_right") or ():
                    wid = sum(12.5 * (1.0 if ord(c) > 0x2E80 else 0.55)
                              for c in str(name))
                    x1 = max(x1, w + 20 + 6 + wid)
                    y0 = min(y0, dy - 9)
                    y1 = max(y1, dy + 5)
                for name, dy in kw.get("pins_left") or ():
                    wid = sum(12.5 * (1.0 if ord(c) > 0x2E80 else 0.55)
                              for c in str(name))
                    x0 = min(x0, -20 - 6 - wid)
                    y0 = min(y0, dy - 9)
                    y1 = max(y1, dy + 5)
        else:
            for name, dy in (kw.get("pins_right") or ()):
                x1 = max(x1, w + 20)
                y1 = max(y1, dy)
            for name, dy in (kw.get("pins_left") or ()):
                x0 = min(x0, -20)
                y1 = max(y1, dy)
        return (x0, y0, x1 + 1, y1 + 1)
    if sym == "swd_header":
        # 以左上角 (x,y) 为参照: 排针本体 w*h, 右侧引脚引线 16px, 标签在上方
        w, h = kw.get("w", 110), kw.get("h", 90)
        return (0, -19, w + 16, h + 1)
    if sym == "pullup":
        # 竖直支路就在 x 上, 元件(电阻+电源箭头)最宽到 x+26; 顶端到 to_y 再上 34
        top = min(kw.get("to_y", 0), 0)
        return (-10, top - 34, 27, 4)
    if sym == "reset_circuit":
        # 节点在中心, 上拉到 vcc(-105), 下拉电容到 ground(+106), 右侧电阻 +70
        return (-22, -140, 80, 115)
    return None


def _tag(svg, sym, cx, cy, **kw):
    """
    给符号的 SVG 外层套一个带 data-sym / data-at / data-kw 的 <g>。

    Doc.add() 拿到它就能反推出包围盒并自动登记 —— 于是**调用方一行都不用改**,
    老的画图脚本重新跑一遍就自动获得了越界/重叠检查能力。
    <g> 是纯透明分组, 渲染结果与不加完全一致。
    """
    import json
    meta = json.dumps(kw, ensure_ascii=False).replace('"', "&quot;")
    return (f'<g data-sym="{sym}" data-x="{cx:.1f}" data-y="{cy:.1f}" '
            f'data-kw="{meta}">{svg}</g>')


def _untag(svg):
    """从 <g data-sym=...> 里取出 (sym, cx, cy, kw)。不是标记过的分组返回 None。"""
    import html
    import json
    import re
    m = re.match(r'<g data-sym="(\w+)" data-x="([\d.-]+)" data-y="([\d.-]+)" '
                 r'data-kw="(.*?)">', svg, re.S)
    if not m:
        return None
    try:
        kw = json.loads(html.unescape(m.group(4)))
    except Exception:
        kw = {}
    return m.group(1), float(m.group(2)), float(m.group(3)), kw


def _auto_bounds(svg):
    """从带标记的符号 SVG 推出绝对坐标包围盒。推不出返回 None。"""
    got = _untag(svg)
    if not got:
        return None
    sym, cx, cy, kw = got
    rel = _needs(sym, **kw)
    if not rel:
        return None
    return (cx + rel[0], cy + rel[1], cx + rel[2], cy + rel[3])


def declare(svg, name, terminals=None, body=None, expect=None, note=None):
    """
    给**自绘符号**声明端子与本体，让 analyze() 能像内置符号一样检查它。

    为什么要这个: analyze() 只认 `wirelib` 里注册过的符号。调用方自己拼的
    元器件（继电器线圈、触点、续流二极管、光敏管、MOS、传感器模块……）
    对检查器是**完全不可见**的 —— 不是"查了没问题"，是"压根没看"。
    后果是这类器件接错（续流管接到基极行、光敏管悬空）能大摇大摆通过电气门。

    用法::

        coil_svg = my_coil(600, 282)
        d.add(declare(coil_svg, "K1线圈",
                      terminals={"t": (600, 252), "b": (600, 312)},
                      body=(586, 254, 614, 310),
                      expect={"b": "集电极"}))

    参数:
        svg       自绘的 SVG 片段
        name      元件名, 用作出现在报错/网表里的标识（建议能一眼认出是哪个器件）
        terminals {端子名: (x, y)} —— **绝对坐标**。电气上该接线的地方,
                  与内置符号的 terminals() 含义一致。analyze() 据此判断
                  悬空 / 旁路 / 短路。
        body      (x0, y0, x1, y1) 本体实心矩形, **绝对坐标**。给了之后
                  analyze() 会检查"有没有导线纵穿本体"（= 该元件被旁路）。
                  位置拿不准就留 None —— 少查一类, 好过乱报。
        expect    {本元件的端子名: 该端子**应该**所在的网络}。
                  目标可写三种形式(推荐第一种):
                    1. **坐标** `(x, y)` —— 目标网络上的任意一点。最稳,
                       不依赖目标元件有没有 label::
                           expect={"a": (446, 152)}      # 该点应在的网
                    2. **电源名** `"+5V"` / `"GND"`
                    3. **"元件名.端子名"** `"K1线圈.b"` —— 该元件必须带 label,
                       否则无法用名字引用(内置符号常不写 label, 请用坐标)。

                  **这是唯一能抓住"接到错的节点上"的手段** —— 接错节点时
                  端子照样"接上了", 悬空/旁路/穿体都不会报, 只有把
                  (实际网络)与(期望网络)比一次才发现。
                  目标名找不到时会明确说清原因(是没这个名字, 还是坐标没落在网上)。
        note      可选说明, 写进 SVG 里供人看。

    未声明的自绘符号会被忽略(与从前行为一致), 所以这是**可选增强**,
    不会让既有脚本报错。但画非标准器件时**强烈建议声明** —— 见 SKILL.md。
    """
    import json
    if not terminals and not body and not expect:
        return svg                       # 什么都没声明, 不必包一层
    rec = {"name": name}
    if terminals:
        rec["terms"] = {k: [round(v[0], 2), round(v[1], 2)]
                        for k, v in terminals.items()}
    if body:
        rec["body"] = [round(v, 2) for v in body]
    if expect:
        rec["expect"] = dict(expect)
    if note:
        rec["note"] = note
    payload = json.dumps(rec, ensure_ascii=False).replace('"', "&quot;")
    return f'<g data-custom="1" data-spec="{payload}">{svg}</g>'


def _custom_specs(svg_text):
    """读出所有 declare() 声明的自绘元件。"""
    import html
    import json
    import re
    out = []
    for m in re.finditer(r'<g data-custom="1" data-spec="(.*?)">', svg_text, re.S):
        try:
            out.append(json.loads(html.unescape(m.group(1))))
        except Exception:
            pass
    return out


# ============================================================
# 端子几何: 每个元件"电气上从哪里接线"
# ============================================================
# 为什么要有这张表: 画图时最常见的致命错误是**引线纵穿元件本体**——
# 竖直电阻的本体占 cy±21 且没有内置引线, 如果接线的竖线从 cy-40 一路
# 拉到 cy+40, 这段线就从电阻身上穿过去了, 等于用一根导线把电阻短路。
# 图上看不出任何异常(就是一根笔直的竖线), verify() 也查不出来。
# 有了端子坐标, check_net.py 就能判断"某条线是否跨过了元件本体"。

# ---- 自绘符号注册表 ----------------------------------------------------
# terminals() / body_box() / chain() 原来只认内置符号(if-elif 硬编码),
# 于是自绘器件(继电器线圈、光敏管、MOS、传感器模块)根本进不了 chain(),
# 调用方只能手算坐标 —— 而手算正是"差几像素没接上"的根源。
# 这里给一个注册入口, 让自绘符号和内建符号平起平坐。
CUSTOM_SYMBOLS = {}


def register_symbol(name, *, terminals=None, body=None):
    """
    注册一个**自绘符号**, 让它能被 `terminals()` / `body_box()` / `chain()`
    识别 —— 也就是能和内置符号一样参与自动排布与电气检查。

    ::

        def my_diode(cx, cy, s=13, **kw):
            svg = f'<polygon points="..." />'
            return svg

        register_symbol("mydiode",
                        terminals=lambda cx, cy, s=13, **kw:
                            {"a": (cx - s, cy), "k": (cx + s, cy)},
                        body=lambda cx, cy, s=13, **kw:
                            (cx - s, cy - s, cx + s, cy + s))

        # 之后就能直接用:
        d.add(my_diode(300, 200))
        chain(d, start, [("D", my_diode, dict(s=13), "D1")])

    参数:
        name       符号名(要和绘制函数的名字一致, `chain()` 按 `__name__` 查找)
        terminals  `f(cx, cy, **kw) -> {端子名: (x, y)}`,**相对 cx/cy 的绝对坐标**
        body       `f(cx, cy, **kw) -> (x0, y0, x1, y1)` 本体矩形; 不给则不做
                   穿体/旁路检查(少查一类, 好过乱报)

    注意: 注册只影响**几何查询**(排版与电气分析)。要把自绘器件的端子
    纳入网表检查, 仍要像以前一样用 `declare(svg, name, terminals=, expect=)`
    把它包起来 —— 两者互补: `register_symbol` 管"能不能自动排布",
    `declare` 管"这个具体实例的端子接对了没有"。

    """
    CUSTOM_SYMBOLS[name] = {"terminals": terminals, "body": body}


def terminals(sym, cx, cy, **kw):
    """
    返回元件的端子坐标 {"名字": (x, y)}。名字是电气含义, 不是引脚号。

    只有**外接引线的端点**(即真正该接线的地方)。元件本体内部的绘制
    线段不算端子。
    """
    if sym == "resistor":
        w_, h_ = kw.get("w", 42), kw.get("h", 15)
        if kw.get("vertical"):
            return {"t": (cx, cy - w_ / 2), "b": (cx, cy + w_ / 2)}
        return {"l": (cx - w_ / 2, cy), "r": (cx + w_ / 2, cy)}
    if sym == "capacitor":
        gap = kw.get("gap", 7)
        plate = kw.get("plate", 15)
        if kw.get("vertical"):
            # 本体: 两板在 cy±gap, 引线再往外 12 -> 外端在 cy±(gap+12)
            return {"t": (cx, cy - gap - 12), "b": (cx, cy + gap + 12)}
        return {"l": (cx - gap - 12, cy), "r": (cx + gap + 12, cy)}
    if sym == "led":
        s, dirn = kw.get("s", 13), kw.get("direction", 1)
        # 阳极尖角侧 / 阴极横线侧
        return {"a": (cx - s * dirn, cy), "k": (cx + s * dirn, cy)}
    if sym == "npn":
        s = kw.get("s", 17)
        d_ = -1 if kw.get("flip") else 1
        # c 与 e 在**同一根 x** 上 —— 两路都竖直走线会叠成一条 VCC→GND 导体
        return {"b": (cx - s * d_, cy),
                "c": (cx + s * d_, cy - s),
                "e": (cx + s * d_, cy + s)}
    if sym == "push_button":
        w_ = kw.get("w", 44)
        return {"a": (cx - w_ / 2, cy), "b": (cx + w_ / 2, cy)}
    if sym == "vcc":
        return {"p": (cx, cy)}            # 接点在下方
    if sym == "ground":
        return {"p": (cx, cy)}            # 接点在上方
    if sym == "power_in":
        return {"p": (cx + 26, cy)}       # 接点在右侧
    if sym == "crystal":
        w_ = kw.get("w", 30)
        return {"l": (cx - w_ / 2, cy), "r": (cx + w_ / 2, cy)}
    if sym == "junction":
        return {"p": (cx, cy)}
    if sym == "pullup":
        # 复合符号: 下端节点 (x,y) 是被上拉的网络; 上端在 to_y 处接电源。
        # 返回空字典的话这一个元件就不会参与连通性检查, 上拉整个漏检。
        return {"net": (cx, cy), "vcc": (cx, kw.get("to_y", cy))}
    if sym == "rgb_led":
        # 三个阴极在左侧按 R/G/B 排开, 公共端在右下 —— 数值与 rgb_led()
        # 实际画出来的引线端点一致。
        s = kw.get("s", 22)
        dy = s * 0.62
        return {"R": (cx - s * 1.585, cy - dy),
                "G": (cx - s * 1.585, cy),
                "B": (cx - s * 1.585, cy + dy),
                "COM": (cx + s * 1.585, cy + dy)}
    if sym == "reset_circuit":
        # 以 NRST 节点为基准: 上拉支路在右侧接过 vcc, 电容在正下方接过 ground
        return {"nrst": (cx, cy), "vcc": (cx + 70, cy - 105),
                "gnd": (cx, cy + 106)}
    # ---- 自绘符号(register_symbol 注册过) ----
    # 放在内置分支之前查: 让调用方能覆盖同名内置符号, 也避免把
    # 注册表查漏在最后那道 return {} 里。
    if sym in CUSTOM_SYMBOLS:
        spec = CUSTOM_SYMBOLS[sym]
        if spec.get("terminals"):
            return spec["terminals"](cx, cy, **kw) or {}
    # mcu_block: 端点**从真实引脚表派生** —— 参数里就有 pins_right/pins_left,
    # 每个引脚引线长 20px。所以不必"造代表点", 算出来的就是实际端点。
    #
    # 早先这里故意返回 {}(怕假悬空), 后果是**电气门对每个 MCU 引脚都是瞎的**:
    # "MCU 引脚悬空/接错"是这类图最常见的真实错误, 却完全查不到。
    # 当时报 20 处假阳性, 是因为给的是硬凑的点; 按引脚表算就不会。
    if sym == "mcu_block":
        w_ = kw.get("w", 190)
        STUB = 20
        out = {}
        for name, dy in (kw.get("pins_right") or ()):
            out[str(name)] = (cx + w_ + STUB, cy + dy)
        for name, dy in (kw.get("pins_left") or ()):
            out[str(name)] = (cx - STUB, cy + dy)
        return out
    # swd_header 仍然不报端子: 它的引脚位置由内部固定布局决定, 而当前把
    # 端点交给调用方用返回值里的字典处理。要补的话得先从绘制代码里把
    # 四个引脚的坐标提出来, 见 quickref 的端子表。
    return {}


def body_box(sym, cx, cy, **kw):
    """
    元件**本体的实心矩形** (x0,y0,x1,y1) —— 不含标签, 不含引线。

    电气校验的核心用途: 任何导线都不该穿过这个矩形。穿过去 = 该元件
    被旁路。与 `_needs()` 的区别是 `_needs()` 管排版(含标签, 宁大勿小),
    这个管电气(只算本体, 必须精确)。
    """
    if sym == "resistor":
        w_, h_ = kw.get("w", 42), kw.get("h", 15)
        if kw.get("vertical"):
            return (cx - h_ / 2, cy - w_ / 2, cx + h_ / 2, cy + w_ / 2)
        return (cx - w_ / 2, cy - h_ / 2, cx + w_ / 2, cy + h_ / 2)
    if sym == "capacitor":
        gap, plate = kw.get("gap", 7), kw.get("plate", 15)
        if kw.get("vertical"):
            return (cx - plate, cy - gap, cx + plate, cy + gap)
        return (cx - gap, cy - plate, cx + gap, cy + plate)
    if sym == "led":
        s, dirn = kw.get("s", 13), kw.get("direction", 1)
        a, k = cx - s * dirn, cx + s * dirn
        return (min(a, k), cy - s, max(a, k), cy + s)
    if sym == "npn":
        s = kw.get("s", 17)
        return (cx - s, cy - s, cx + s, cy + s)
    if sym in CUSTOM_SYMBOLS and CUSTOM_SYMBOLS[sym].get("body"):
        return CUSTOM_SYMBOLS[sym]["body"](cx, cy, **kw)
    return None


# ============================================================
# 网表连通性分析
# ============================================================
# 这是 verify() 补不上的另一半: verify() 查"排版好不好看", 这里查
# "电路对不对"。短路、元件被旁路、偏置网络没接上 —— 这三类错误在图上
# 都只是一根普通的线, 肉眼和排版检查都发现不了。

def _drawn_extent(group_svg):
    """
    量出一个 SVG 分组的**实际绘制极值** (x0, y0, x1, y1), 量不到返回 None。

    用于自绘符号的几何一致性检查: `declare()` 里的 terminals/body 是**作者手填的
    绝对坐标**, 与符号内部的绘制代码之间没有任何一致性约束 —— 于是可能"声明的
    端子"飘在"画出来的图形"外面 17px, 而检查器完全看不出来(那一组几何被
    `_extract_netlist` 整组剔除, 它只知道端子声明在哪)。

    量法与 measure_symbols.py 一致: line / rect / circle / polygon / text 的极值。
    """
    import re
    xs, ys = [], []
    for m in re.finditer(r'<line[^>]*x1="([\d.-]+)"[^>]*y1="([\d.-]+)"'
                         r'[^>]*x2="([\d.-]+)"[^>]*y2="([\d.-]+)"', group_svg):
        xs += [float(m.group(1)), float(m.group(3))]
        ys += [float(m.group(2)), float(m.group(4))]
    for m in re.finditer(r'<rect[^>]*x="([\d.-]+)"[^>]*y="([\d.-]+)"'
                         r'[^>]*width="([\d.-]+)"[^>]*height="([\d.-]+)"', group_svg):
        x, y, w_, h_ = (float(m.group(i)) for i in (1, 2, 3, 4))
        xs += [x, x + w_]
        ys += [y, y + h_]
    for m in re.finditer(r'<circle[^>]*cx="([\d.-]+)"[^>]*cy="([\d.-]+)"'
                         r'[^>]*r="([\d.-]+)"', group_svg):
        cx, cy, r_ = float(m.group(1)), float(m.group(2)), float(m.group(3))
        xs += [cx - r_, cx + r_]
        ys += [cy - r_, cy + r_]
    for m in re.finditer(r'<polygon[^>]*points="([^"]+)"', group_svg):
        for pair in m.group(1).split():
            if "," in pair:
                px, py = pair.split(",")[:2]
                try:
                    xs.append(float(px))
                    ys.append(float(py))
                except ValueError:
                    pass
    # path: 逐个命令解析。**不能**用宽松正则扫数字 ——
    # 弧 `A rx ry rot laf sf x y` 里前四个也是数字, 宽松匹配会把半径、
    # 标志位当成坐标(实测: 把 `A 10.5 10.5 0 0 1 760 380` 读成 (1,760)),
    # 于是极值算错、正常的端子被误报。
    for m in re.finditer(r'<path[^>]*d="([^"]+)"', group_svg):
        for cmd, args in re.findall(r'([MLAHVmlahv])([^MLAHVmlahv]*)', m.group(1)):
            nums = re.findall(r'-?\d*\.?\d+', args)
            try:
                if cmd in "MLml" and len(nums) >= 2:
                    xs.append(float(nums[0]))
                    ys.append(float(nums[1]))
                elif cmd in "Aa" and len(nums) >= 7:
                    # 最后两个才是目标点
                    xs.append(float(nums[-2]))
                    ys.append(float(nums[-1]))
                elif cmd in "Hh" and nums:
                    xs.append(float(nums[0]))
                elif cmd in "Vv" and nums:
                    ys.append(float(nums[0]))
            except ValueError:
                pass
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _pt_seg_dist(px, py, x1, y1, x2, y2):
    """点到线段的距离。"""
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


def _dist_to_drawn(px, py, group_svg):
    """
    点到该分组里**任意绘制特征**的最近距离。落在线段/多边形边上为 0;
    落在 rect/circle/polygon 的**内部**也算 0(实心图形, 端子在体内是正常的)。

    用于自绘符号的端子检查: 端子若离所有绘制特征都远, 就是"飘在空白处"
    —— 那正是实测踩到的坑(线圈端子悬在弧外 17px, 连通性完美, 图上像没接线)。
    比"是否在包围盒内"更准: 包围盒内的空洞也能抓出来。
    """
    import re
    d = 1e9

    for m in re.finditer(r'<line[^>]*x1="([\d.-]+)"[^>]*y1="([\d.-]+)"'
                         r'[^>]*x2="([\d.-]+)"[^>]*y2="([\d.-]+)"', group_svg):
        d = min(d, _pt_seg_dist(px, py, *(float(m.group(i)) for i in (1, 2, 3, 4))))

    for m in re.finditer(r'<rect[^>]*x="([\d.-]+)"[^>]*y="([\d.-]+)"'
                         r'[^>]*width="([\d.-]+)"[^>]*height="([\d.-]+)"', group_svg):
        x, y, w_, h_ = (float(m.group(i)) for i in (1, 2, 3, 4))
        if x - 1 <= px <= x + w_ + 1 and y - 1 <= py <= y + h_ + 1:
            d = 0.0                     # 实心/框内
        else:
            d = min(d, _pt_seg_dist(px, py, x, y, x + w_, y),
                    _pt_seg_dist(px, py, x, y + h_, x + w_, y + h_),
                    _pt_seg_dist(px, py, x, y, x, y + h_),
                    _pt_seg_dist(px, py, x + w_, y, x + w_, y + h_))

    for m in re.finditer(r'<circle[^>]*cx="([\d.-]+)"[^>]*cy="([\d.-]+)"'
                         r'[^>]*r="([\d.-]+)"', group_svg):
        cx, cy, r_ = (float(m.group(i)) for i in (1, 2, 3))
        d = min(d, max(0.0, ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 - r_))

    for m in re.finditer(r'<polygon[^>]*points="([^"]+)"', group_svg):
        pts = []
        for pair in m.group(1).split():
            if "," in pair:
                try:
                    a, b = pair.split(",")[:2]
                    pts.append((float(a), float(b)))
                except ValueError:
                    pass
        if len(pts) >= 2:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if min(xs) - 1 <= px <= max(xs) + 1 and min(ys) - 1 <= py <= max(ys) + 1:
                d = 0.0                 # 实心多边形, 落在顶点范围内算贴上
            else:
                for i in range(len(pts)):
                    a, b = pts[i], pts[(i + 1) % len(pts)]
                    d = min(d, _pt_seg_dist(px, py, a[0], a[1], b[0], b[1]))

    # path: 用各命令的坐标对近似折线(弧按弦近似, 所以判定时留容差)
    for m in re.finditer(r'<path[^>]*d="([^"]+)"', group_svg):
        prev, cur = None, None
        for cmd, args in re.findall(r'([MLAHVmlahv])([^MLAHVmlahv]*)', m.group(1)):
            nums = re.findall(r'-?\d*\.?\d+', args)
            try:
                if cmd in "MLml" and len(nums) >= 2:
                    cur = (float(nums[0]), float(nums[1]))
                elif cmd in "Aa" and len(nums) >= 7:
                    cur = (float(nums[-2]), float(nums[-1]))
                elif cmd in "Hh" and nums:
                    cur = (float(nums[0]), prev[1] if prev else py)
                elif cmd in "Vv" and nums:
                    cur = (prev[0] if prev else px, float(nums[0]))
                else:
                    continue
            except ValueError:
                continue
            if prev and cur:
                d = min(d, _pt_seg_dist(px, py, prev[0], prev[1], cur[0], cur[1]))
            prev = cur
    return d


def _dangling_custom_terms(svg_text, tol=6.0):
    """
    找出**自绘符号里声明了、但离画出来的图形太远的端子**。

    为什么需要这一类: `declare(terminals=...)` 是作者手填的绝对坐标, 与符号内部
    绘制代码之间**没有任何一致性约束**。内置符号有 `measure_symbols.py` 校准,
    自绘符号没有 —— 它是整套体系里唯一还靠"人写对"的一环。

    实测踩过: 继电器线圈声明端子跨 cx±38, 但画弧的代码只跨 cx±21,
    两个端子各悬在图形外 17px 的空白处。导线**确实**接到了声明的端点上
    (连通性完美), 但那里什么都没有 —— 图上看到的是"线圈两端没接线"。
    短路/旁路/穿体/悬空/接错**全都不报**, 因为端子确实碰到了导线。

    判据是**到最近绘制特征的距离**, 不是"是否在包围盒内" —— 后者抓不到
    包围盒内部的空洞(图形中间空着一块的地方)。
    返回 [(元件名, 端子名, (x,y), 到图形多远, 图形极值)]
    """
    import re
    out = []
    for m in re.finditer(r'<g data-custom="1" data-spec="(.*?)">', svg_text, re.S):
        import html as _h
        import json as _j
        try:
            spec = _j.loads(_h.unescape(m.group(1)))
        except Exception:
            continue
        # 取本组的完整内容 —— 用**深度配对**而不是非贪婪 .*?</g>:
        # 复合自绘器件内部还嵌着别的 <g>, 非贪婪会在内层 </g> 处提前收尾,
        # 量出来的极值就偏小(于是本来正常的端子被误报)。
        depth, start, inner = 0, None, ""
        for mm in re.finditer(r'<g\b[^>]*>|</g>', svg_text[m.end():]):
            if mm.group(0).startswith("<g"):
                if depth == 0:
                    start = mm.start()
                depth += 1
            else:
                depth -= 1
                if depth == 0 and start is not None:
                    inner += svg_text[m.end() + start:m.end() + mm.end()]
                    start = None
        if not inner:
            # 没有嵌套分组: 直接取到第一个 </g>
            e = svg_text.find("</g>", m.end())
            inner = svg_text[m.end():e if e > 0 else len(svg_text)]
        ext = _drawn_extent(inner)
        if not ext:
            continue
        name = spec.get("name", "自绘元件")
        for tname, tv in (spec.get("terms") or {}).items():
            tx, ty = float(tv[0]), float(tv[1])
            dist = _dist_to_drawn(tx, ty, inner)
            if dist > tol:
                out.append((name, tname, (tx, ty), dist, ext))
    return out


def _extract_netlist(svg_text):
    """
    从 SVG 里抽出连线图: 线段 / 结点 / 元件端子。

    关键规则(**决定成败**): **端点相接才算连接; 中途交叉不算** ——
    除非交点处有 junction 圆点。不守这条规矩, 两条只是视觉上交叉的
    导线会被判成连通, 于是报出一堆"分压网络短路"的假阳性, 比不查还糟。
    """
    import json
    import html
    import re
    lines, dots, comps = [], [], []
    # 0) 先把元件分组从"导线源码"里剔除干净。
    #    元件内部的绘制线段(比如 npn 的斜引线、基极竖线)不是导线 —— 把它们
    #    当导线会凭空造出连接, 也会让斜线干扰正交判断。本次实测: 152 条
    #    <line> 里有 27 条是符号内部几何, 混进来就全乱。
    #
    #    注意**必须按嵌套深度配对**, 不能用非贪婪的 .*?</g>: pullup() 这类
    #    复合符号内部还嵌着 resistor 的 <g data-sym>, 非贪婪匹配会在内层
    #    的 </g> 处就收尾, 于是内层元件的开标签留在源码里被当成独立元件
    #    —— 结果是每个上拉电阻都被报一次"穿体"假阳性。
    groups, depth, start = [], 0, None
    for m in re.finditer(r'<g\b[^>]*data-sym="\w+"[^>]*>|</g>', svg_text):
        if m.group(0).startswith("<g"):
            if depth == 0:
                start = m.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(svg_text[start:m.end()])
                start = None

    # 元件登记: 只收**最外层**分组的符号(内层的属于复合符号的一部分,
    # 它的几何已经由外层符号的 terminals()/body_box() 一并表达)。
    inner_spans = []
    for g in groups:
        for m in re.finditer(r'<g\b[^>]*data-sym="\w+"[^>]*>', g):
            if m.start() != 0:
                inner_spans.append((g, m.start()))

    for m in re.finditer(r'<g data-sym="(\w+)" data-x="([\d.-]+)" data-y="([\d.-]+)" '
                         r'data-kw="(.*?)">', svg_text, re.S):
        # 跳过嵌套在内层的位置: 它前面紧邻的字符是外层分组内容的一部分
        pre = svg_text[max(0, m.start() - 400):m.start()]
        if pre.rfind("<g data-sym=") > pre.rfind("</g>"):
            continue
        sym, cx, cy = m.group(1), float(m.group(2)), float(m.group(3))
        try:
            kw = json.loads(html.unescape(m.group(4)))
        except Exception:
            kw = {}
        terms = terminals(sym, cx, cy, **kw)
        if terms:
            comps.append({"sym": sym, "x": cx, "y": cy, "kw": kw,
                          "terms": terms, "body": body_box(sym, cx, cy, **kw)})

    # ---- 调用方 declare() 过的自绘元件 ----
    # 这些是 wirelib 不认识的器件（继电器线圈、续流管、光敏管……）。
    # 不把它们收进来, 检查器对它们就是瞎的 —— 那是最危险的漏检:
    # 不是"查了没问题", 是"压根没看"。
    custom_groups = re.findall(r'<g data-custom="1"[^>]*>.*?</g>', svg_text, re.S)
    for spec in _custom_specs(svg_text):
        terms = {k: (v[0], v[1]) for k, v in (spec.get("terms") or {}).items()}
        body = tuple(spec["body"]) if spec.get("body") else None
        comps.append({"sym": "custom", "x": 0.0, "y": 0.0,
                      "kw": {"label": spec.get("name", "自绘元件")},
                      "terms": terms, "body": body})

    wire_src = svg_text
    for g in groups + custom_groups:
        wire_src = wire_src.replace(g, "", 1)

    # 1) 真实导线。两件必须过滤掉的东西:
    #    - data-deco: 网格线/分隔线/功能块外框。网格线画满整张图, 不过滤
    #      的话每根都被当成导线, 连通性分析全是假的。
    #    - 斜线: 只认正交(水平/竖直)线段。斜线在本库里只出现在元件内部
    #      和手绘装饰上, 参与了会让"交叉判定"失去意义。
    for m in re.finditer(
            r'<line((?:(?!data-deco)[^>])*?)x1="([\d.-]+)" y1="([\d.-]+)" '
            r'x2="([\d.-]+)" y2="([\d.-]+)"', wire_src):
        x1, y1, x2, y2 = (float(m.group(i)) for i in (2, 3, 4, 5))
        if abs(x1 - x2) < 0.6 or abs(y1 - y2) < 0.6:
            lines.append((x1, y1, x2, y2))

    # 畸形线段(坐标不是数字)一律被上面的正则漏掉 —— 静默丢弃。这里单独
    # 记数, 由 analyze() 报出去。
    bad_lines = _malformed_lines(wire_src)

    # 2) junction 圆点: 有它才算"这里真的连上了"
    for m in re.finditer(r'<circle(?:(?!data-node)[^>])*?cx="([\d.-]+)" '
                         r'cy="([\d.-]+)" r="([\d.-]+)"', wire_src):
        r_ = float(m.group(3))
        if r_ <= 5:                       # junction() 用 r=3.5; 大圆是器件/节点标签
            dots.append((float(m.group(1)), float(m.group(2))))

    return lines, dots, comps, bad_lines


def _malformed_lines(svg_text):
    """
    找出坐标不是数字的 `<line>` —— 它们会被 `_extract_netlist` **静默丢弃**。

    为什么要专门查: 这类错误的表现极具误导性。实测踩过的一次 —— 调用方写了
    `x, y = x, y`，而 `x` 恰好绑到了从 `wirelib import *` 带进来的颜色常量
    `WIRE = "#37474f"`，于是画出 `<line x1="#37474f" .../>`。脚本正常退出、
    SVG 能打开、坐标看着"有值"，但解析正则要求数字，这条线就消失了。

    后果不是"少一条线"这么简单: 元件端子还按原坐标挂在一条**不存在的导线**
    上, 于是报出一整片 [悬空]/[旁路]/[穿体]。真正的病因(一个变量遮蔽)被埋在
    几十条假问题下面, 极难定位。

    返回 [{x1,y1,x2,y2,raw}, ...]。analyze() 会把它作为 `[畸形]` 报出来。
    """
    import re
    bad = []
    for m in re.finditer(r'<line((?:(?!data-deco)[^>])*?)/>', svg_text):
        attrs = m.group(1)
        if "data-deco" in attrs:
            continue
        got = {}
        for k in ("x1", "y1", "x2", "y2"):
            mm = re.search(k + r'="([^"]*)"', attrs)
            if not mm:
                got[k] = None
                continue
            v = mm.group(1).strip()
            try:
                float(v)
                got[k] = v
            except ValueError:
                got[k] = v            # 存在但不是数字 -> 畸形
        # 只报"该有坐标却不是数字"的; 上下文的圆/矩形不走这条
        if any(got[k] is not None and not _isnum(got[k]) for k in got):
            bad.append(got)
    return bad


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _on_segment(px, py, x1, y1, x2, y2, tol=0.8):
    """点是否落在线段上(含端点)。"""
    if abs(x1 - x2) < 0.6:                          # 竖线
        return abs(px - x1) <= tol and min(y1, y2) - tol <= py <= max(y1, y2) + tol
    if abs(y1 - y2) < 0.6:                          # 横线
        return abs(py - y1) <= tol and min(x1, x2) - tol <= px <= max(x1, x2) + tol
    return False


def _seg_cross(a, b):
    """两条正交线段是否交叉(不含共线情形)。"""
    (ax1, ay1, ax2, ay2), (bx1, by1, bx2, by2) = a, b
    a_vert = abs(ax1 - ax2) < 0.6
    b_vert = abs(bx1 - bx2) < 0.6
    if a_vert == b_vert:
        return None
    v, h = (a, b) if a_vert else (b, a)
    vx, vy0, vy1 = v[0], min(v[1], v[3]), max(v[1], v[3])
    hy, hx0, hx1 = h[1], min(h[0], h[2]), max(h[0], h[2])
    if hx0 - 0.8 <= vx <= hx1 + 0.8 and vy0 - 0.8 <= hy <= vy1 + 0.8:
        return (vx, hy)
    return None


def net2svg(d, nets, parts, origin=(200, 200), gap=90, row=140,
            title="", subtitle="", w=1180, h=760):
    """
    **网表驱动布局**: 只描述"哪些端子连在一起", 坐标全部由程序算。

    这条路要解决的是根本问题 —— 调用方(尤其是 AI)手写坐标时, 只要一个数字
    错几像素就断路, 而图上看不出来。前面几轮优化(`place()`、`chain()`)都只是
    "帮它少写几个数字", 但**只要 API 有缝它就会绕回手算**。这里换成: 干脆
    不给写坐标的机会。

    ::

        parts = [
            ("R1",   "resistor", dict(w=42, h=15), "1K"),
            ("LED1", "led",      dict(s=13),       "红色"),
        ]
        nets = [
            ("VCC", ["R1.l"]),          # 网络名 VCC/GND 会自动补电源/地符号
            ("n1",  ["R1.r", "LED1.a"]),
            ("GND", ["LED1.k"]),
        ]
        net2svg(d, nets, parts, title="LED 指示")

    参数:
        nets   [(网络名, [端子全名, ...]), ...]
               端子全名 = "元件名.端子名"; 端子名取自 `terminals()`
               (resistor: l/r, led: a/k, capacitor: l/r, npn: b/c/e,
                电源/地: p)。
               网络名为 `VCC`/`+3.3V`/`+5V` 时自动补电源符号, 为 `GND*`
               时自动补接地符号 —— 不用写进 parts。
        parts  [(元件名, 符号函数或内置符号名, 参数dict, 标注文字), ...]
        origin 起点; gap 同一行里相邻元件的净间距; row 行距
        w/h    画布尺寸

    返回 {"pos": {元件名: (cx,cy)}, "nets": {网络名: [(x,y),...]}}

    **布局模型**(刻意简单, 不做通用布线):
      - 一个网络里若有两个元件端子, 就把它们**排在同一行相邻的位置**;
      - 两端元件横放, 左端子接"左边那个网络", 右端子接"右边那个网络";
      - 电源/地这类"单端子网络"放在行的最左/最右端, 作为支路的起止;
      - 一条支路 = 从电源出发、经若干元件、到地。

    于是 **AI 只需要声明连接关系, 不需要任何数字**(除了可选的 gap/row)。

    **已知限制(实测)**: 当前只可靠支持**一条主干**(串联 + 两端接电源/地)。
    一个节点若有 **3 个及以上**元件端子, 需要"竖直母线 + 各支路横向挂出"的
    结构, 本函数排不出来(会把它们摆成一行, 于是某些端子连不上)。
    这类电路要么拆成多条 net2svg 调用分别画主干, 要么仍用 chain()/手绘。
    通用布线器是几百行的东西, 而且排出来人看不懂 —— 这里刻意不做。
    """
    # ---------- 1) 拆出每个端子的归属 ----------
    owner = {}          # "R1.r" -> net
    for net, members in nets:
        for full in members:
            owner[full] = net

    # ---------- 1b) 分支节点检查：3 个及以上端子汇于一个网络 ----------
    # 本函数的布局模型是"一条主干, 同网络的元件排成一行"。一个节点接
    # 3 路以上时, 排在中间的元件两端各接不同的网, 而"该节点"只剩一处
    # 可连 —— 必然有端子接不上。所以这里**提前报错并指向 bus_net()**,
    # 而不是照样画出来再让电气门报一片悬空(实测 3 路会留下 4 处悬空,
    # 而且看着像"工具坏了", 实则是用错了工具)。
    for net, members in nets:
        # 端子数 = 支路数; 同一元件的两个端子各算一路
        if len(members) >= 3 and not _is_power(net):
            raise ValueError(
                f"net2svg(): 网络 {net!r} 汇集了 {len(members)} 个端子 "
                f"({', '.join(members)}) —— 这是**分支节点**, 本函数排不出来。\n"
                f"        改用 bus_net(d, cx=..., branches=[...]) —— "
                f"一根竖直母线 + 各支路横向挂出。\n"
                f"        或把该节点拆开: 用 net2svg 画一条主干, 分支另画。")

    # ---------- 2) 定行: 按 parts 的声明顺序, 每条"链"占一行 ----------
    # 用并查集把元件按"共享网络"分组 —— 同一组的元件排在同一行。
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for net, members in nets:
        names = [m.split(".")[0] for m in members]
        for n in names[1:]:
            union(names[0], n)
    groups = {}
    for name, sym, kw, label in parts:
        groups.setdefault(find(name), []).append(name)

    # ---------- 3) 逐行排布 ----------
    kinds = _sym_kinds()
    pos, net_pts = {}, {}
    for gi, (root, names) in enumerate(groups.items()):
        y = origin[1] + gi * row

        # 该行涉及的网络, 按"从电源到地"排序
        involved = [nm for nm, ms in nets
                    if any(m.split(".")[0] in names for m in ms)]
        involved.sort(key=lambda nm: (0 if _is_gnd(nm) else
                                      1 if _is_vcc(nm) else 2))

        # 单端子网络(电源/地)放两端; 元件依次排开
        x = origin[0]
        for net in involved:
            ms = nets_dict(nets, net)
            if len(ms) == 1 and _is_power(net):
                net_pts.setdefault(net, []).append((x, y))
                x += gap

        for name in names:
            sym = dict((n, sy) for n, sy, _, _ in parts)[name]
            kw = dict((n, k or {}) for n, _, k, _ in parts)[name]
            sname = getattr(sym, "__name__", sym)
            t = terminals(sname, 0, 0, **kw)
            if not t:
                raise ValueError(f"net2svg(): {sname} 没有端子定义")
            left_tn = min(t, key=lambda n: t[n][0])
            right_tn = max(t, key=lambda n: t[n][0])
            x += gap
            cx = x - t[left_tn][0]
            fn = sym if callable(sym) else globals().get(sym)
            svg = fn(cx, y, **kw)
            if isinstance(svg, tuple):
                svg = svg[0]
            d.add(svg)
            pos[name] = (cx, y)
            for tn in t:
                net_pts.setdefault(owner.get(f"{name}.{tn}", "_"), []).append(
                    (cx + t[tn][0], y + t[tn][1]))
            x += (t[right_tn][0] - t[left_tn][0])

        mcu_shift = 0
        # 行尾的单端子电源/地网络
        for net in involved:
            ms = nets_dict(nets, net)
            if len(ms) == 1 and _is_power(net) and net_pts.get(net) == []:
                pass

    # ---------- 4) 导线 ----------
    # 只连**同一行、同一网络**里相邻且确实有间隙的两点。
    # 关键: 不能无脑连"同一网络的所有点" —— 元件的两个端子会落进各自的网络,
    # 而它俩在同一行上, 一条横线连过去就从元件本体上穿过去了 (= 把它短路)。
    # 所以这里先算"元件占用的 x 区间", 只有跨过空档的连线才画。
    occupied = []
    for name, (cx, cy) in pos.items():
        sym = dict((n, sy) for n, sy, _, _ in parts)[name]
        kw = dict((n, k or {}) for n, _, k, _ in parts)[name]
        sname = getattr(sym, "__name__", sym)
        t = terminals(sname, cx, cy, **kw)
        xs = [p_[0] for p_ in t.values()] if t else [cx]
        occupied.append((min(xs), max(xs)))

    def blocked(x0, x1):
        for (a, b) in occupied:
            if x0 < b - 1 and x1 > a + 1:      # 与某元件区间相交
                return True
        return False

    for net, pts in net_pts.items():
        if net == "_":
            continue
        row_pts = sorted(pts)
        for a, b in zip(row_pts, row_pts[1:]):
            if abs(a[1] - b[1]) > 0.6:
                continue
            if a[0] == b[0]:
                continue
            if blocked(a[0], b[0]):
                continue                        # 这段被元件占了, 不画
            d.add(line(a[0], a[1], b[0], b[1], WIRE, 2))

    # ---------- 5) 电源/地符号 ----------
    for net, ms in nets:
        pts = net_pts.get(net) or []
        if not pts or not _is_power(net):
            continue
        if _is_gnd(net):
            px, py = max(pts)[0], max(pts)[1]
            d.add(line(px, py, px, py + 34, WIRE, 2))
            d.add(ground(px, py + 34))
        else:
            px, py = min(pts)[0], min(pts)[1]
            d.add(line(px - 56, py, px, py, WIRE, 2))
            d.add(power_in(px - 56, py, net if net.startswith("+") else "+5V"))
    return {"pos": pos, "nets": net_pts}


def bus_net(d, cx, y0, y1, branches, label=None):
    """
    **竖直母线 + 四向挂支路** —— 解决 net2svg() 排不了的分支节点。

    真实电路里最麻烦的形状不是串联主干, 而是"一个节点接 3~4 个元件"::

        分压点 A ── D1 / R1 / RV1          (3 路)
        集电极  ── RLY / D2 / Q1.c          (3 路)
        5V 母线 ── RLY / D2 / R3            (3 路)

    net2svg() 把同网络的元件摆成一行, 于是这些节点的端子连不上。这里换个
    结构: **画一根竖直母线, 每个支路从母线上指定位置沿指定方向引出去。**

    ::

        r = bus_net(d, cx=400, y0=200, y1=660, label="A", branches=[
            ("D1",  "up",   0.00, "led",      dict(s=13, direction=1), "光敏"),
            ("R1",  "down", 0.35, "resistor", dict(w=42, h=15), "10K"),
            ("RV1", "down", 0.65, "resistor", dict(w=42, h=15), "10K"),
        ])

    参数:
        cx, y0, y1  母线所在 x, 以及上下端
        branches    [(键, 方向, 位置比, 符号, 参数dict, 标注), ...]
                    - 方向: "up" / "down" / "left" / "right"
                    - 位置比 0..1: 支路接在母线哪个高度(left/right 用作纵向定位)
        label       母线所属网络名, 标在母线旁; None 则不标

    返回 {"net": [(x,y),(x,y)], "ends": {键: (x,y)}, "terms": {键: {端子: (x,y)}}}

    母线画成一条竖线, 支路从它上面引出去, 接入处自动打 junction。
    **端点全部由 terminals() 算**, 所以 analyze() 一定认得。
    """
    out = {"net": [(cx, y0), (cx, y1)], "ends": {}, "terms": {}}

    d.add(line(cx, y0, cx, y1, WIRE, 2))
    if label:
        place(d, cx, (y0 + y1) / 2, label, prefer="left")

    for br in branches:
        # 支路可以是 6 元组 (键, 方向, 位置比, 符号, 参数, 标注),
        # 也可以多给第 7 项 = **挂到母线的是哪个端子**。
        # 不给时按方向自动挑(见下)。多水平端子的符号(如 rgb_led 的
        # R/G/B/COM)必须显式指定, 否则"自动挑最左端"可能不是你想要的。
        if len(br) >= 7:
            key, direction, ratio, sym, kw, note, attach = br[:7]
        else:
            key, direction, ratio, sym, kw, note = br
            attach = None
        kw = dict(kw or {})
        sname = getattr(sym, "__name__", sym)
        t = terminals(sname, 0, 0, **kw)
        if not t:
            raise ValueError(f"bus_net(): {sname} 没有端子定义")
        fn = sym if callable(sym) else globals().get(sym)

        tap = y0 + (y1 - y0) * ratio

        # 支路一律**从母线横着让开一段**再放元件 —— 绝不能把元件本体压在
        # 母线上。母线是一条连续的竖线, 任何"本体骑在母线上"的元件都会被它
        # 纵穿 (= 该元件被旁路)。实测过一次: 竖放的电阻直接挂在母线上,
        # 母线从它身上穿过去, 报 [穿体]。
        # 所以: 元件放在母线一侧, 用一段引线把"朝向母线的那个端子"接回来。
        if attach is not None:
            if attach not in t:
                raise ValueError(f"bus_net(): {sname} 没有端子 {attach!r} —— "
                                 f"可用的是 {sorted(t)}")
            tn = attach
            if abs(t[tn][1]) >= 1:
                # 非水平端子(如 npn 的 c/e 同在上/下): 挂上去要竖着拐,
                # 仍然可行, 由下面的折线逻辑处理。
                pass
        else:
            horiz = [n for n in t if abs(t[n][1]) < 1]
            if not horiz:
                raise ValueError(f"bus_net(): {sname} 没有水平端子, "
                                 f"无法横着挂在母线侧面（可显式给第 7 项指定端子）")
            tn = None
        if direction in ("up", "down"):
            # 竖直支路: 元件仍横放, 整体排在母线的上/下方。
            # 元件要横跨两个横端子中的一个来挂 —— 统一取左端子 tn, 引线从
            # 母线拐到它上面。
            if tn is None:
                tn = min(horiz, key=lambda n: t[n][0])
            cx_ = cx + 52 - t[tn][0]              # 左端子离母线 52px
            # 元件的 y: 让 tn 这个端子落在接入点上方/下方 GAP 处。
            # **必须减掉 t[tn][1]** —— 它是端子相对元件中心的纵向偏移。
            # 早先写成 `cy = tap - 68` 忘了减, 结果元件整体偏离接入点
            # 68px 再叠加端子偏移, 越到母线下方偏得越多。
            off = 68 if direction == "up" else -68
            cy = tap + off - t[tn][1]
        else:
            if tn is None:
                tn = (min if direction == "right" else max)(horiz, key=lambda n: t[n][0])
            cx_ = cx + (52 if direction == "right" else -52) - t[tn][0]
            cy = tap - t[tn][1]

        tt = _draw_part(d, fn, cx_, cy, kw, name=key)
        out["terms"][key] = tt
        # 从母线接入点 (cx, tap) 折到元件朝向母线的那个端子
        lp = tt[tn]
        d.add(line(cx, tap, lp[0], tap, WIRE, 2))        # 先横
        if abs(lp[1] - tap) > 0.8:
            d.add(line(lp[0], tap, lp[0], lp[1], WIRE, 2))  # 再竖
        d.add(junction(cx, tap))
        far = max(tt.items(), key=lambda kv: abs(kv[1][0] - cx) + abs(kv[1][1] - tap))
        out["ends"][key] = far[1]
        if note:
            place(d, cx_, cy, note)
    return out


def link(d, a, b, mode="hv", junction_at=None, mid=None):
    """
    用正交折线把两个点连起来 —— **母线之间、母线到 MCU 的连接用这个,
    不要手写 `d.add(line(...))`**。

    为什么需要: `chain()` / `bus_net()` 各自负责一段支路, 但**它们之间**的
    连线此前必须自己算坐标(交出这次会话大部分"差几像素"的机会)。
    这里把那段也纳入工具: 只给两个端点, 拐弯自动算。

    ::

        # 母线到 MCU 的引脚
        link(d, bus["ends"]["R1"], ends["PA0"])
        # 两条母线
        link(d, (cx1, y1), (cx2, y2), mode="vh")

    参数:
        a, b        两个端点 (x, y)。**用符号返回值 / terminals() 取**,
                    不要手填 —— 这正是本函数要消灭的东西。
        mode        拐弯方式:
                      "hv"  先水平后垂直(默认)
                      "vh"  先垂直后水平
                      "h"   只走水平(要求 y 相等, 否则报错)
                      "v"   只走垂直(要求 x 相等, 否则报错)
                      "auto" 选折线更短的那个
        junction_at T 型接头的位置, 给 "a" / "b" / "mid" 时打 junction 圆点。
                    **两条线共端点不用打点**; 一端落在另一条的**中途**才需要。
        mid         三点连接时的中间拐点 (x, y)(可选, 用于强制走某条通道)。

    返回 {"path": [(x,y), ...], "end": b} —— 便于接着往下接。
    """
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])

    if mode == "h" and abs(ay - by) > 0.8:
        raise ValueError(f"link(mode='h'): 两端 y 不同 ({ay:.1f} vs {by:.1f}), "
                         f"水平连不上 —— 改用 'hv' 或 'vh'")
    if mode == "v" and abs(ax - bx) > 0.8:
        raise ValueError(f"link(mode='v'): 两端 x 不同 ({ax:.1f} vs {bx:.1f}), "
                         f"垂直连不上 —— 改用 'hv' 或 'vh'")

    if mode in ("hv", "auto") or (mode == "h" and abs(ay - by) <= 0.8):
        # 先横后竖: 拐点在 (bx, ay)
        pts = [(ax, ay), (bx, ay), (bx, by)]
    else:
        # 先竖后横: 拐点在 (ax, by)
        pts = [(ax, ay), (ax, by), (bx, by)]

    if mid is not None:
        pts = [(ax, ay), (mid[0], mid[1]), (bx, by)]

    # 去掉共线的中点(两点重合或三点一线时, 少画一段零长度/重叠的线)
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 0.4 or abs(p[1] - clean[-1][1]) > 0.4:
            clean.append(p)

    if len(clean) >= 2:
        d.add(*[line(clean[i][0], clean[i][1], clean[i + 1][0], clean[i + 1][1],
                     WIRE, 2) for i in range(len(clean) - 1)])
    else:
        # 两点重合: 不画线(画了也是零长度)。但要提醒 —— 这通常意味着
        # 调用方把"已经接上的两个端子"又连了一次, 或坐标算错了。
        print(f"  [link] 起止点重合 ({ax:.0f},{ay:.0f}), 未画线")

    jp = {"a": (ax, ay), "b": (bx, by),
          "mid": clean[1] if len(clean) > 2 else None}.get(junction_at)
    if jp:
        d.add(junction(jp[0], jp[1]))
    return {"path": clean, "end": b}


def _draw_part(d, fn, cx, cy, kw, name=None, expect=None):
    """
    画一个元件并登记。**自绘符号会自动包进 declare()** —— 否则它的内部几何
    会被 `_extract_netlist` 当成真实导线, 而且 `analyze()` 完全看不见它。

    `chain()` / `bus_net()` 都走这里, 所以自绘符号在这两个工具里也能正常用。
    """
    svg = fn(cx, cy, **(kw or {}))
    if isinstance(svg, tuple):
        svg = svg[0]
    sname = getattr(fn, "__name__", fn)
    t = terminals(sname, cx, cy, **(kw or {}))
    if sname in CUSTOM_SYMBOLS and name:
        # 自绘符号: 声明端子/本体/期望连接, 让检查器认得
        d.add(declare(svg, name, terminals=t,
                      body=body_box(sname, cx, cy, **(kw or {})),
                      expect=expect))
    else:
        d.add(svg)
    return t


def _is_custom(fn):
    return getattr(fn, "__name__", fn) in CUSTOM_SYMBOLS


def nets_dict(nets, want):
    for nm, ms in nets:
        if nm == want:
            return ms
    return []


def _is_gnd(net):
    return net.upper().startswith("GND")


def _is_vcc(net):
    n = net.upper()
    return n in ("VCC", "VDD") or n.startswith("+")


def _is_power(net):
    return _is_gnd(net) or _is_vcc(net)


def _sym_kinds():
    return {}


def analyze(svg_path, quiet=False):
    """
    网表连通性分析。返回 dict:

      {"vcc_gnd_shorted": bool,       # VCC 与 GND 同网 —— 必报
       "nets": {网号: [成员名, ...]},
       "members": {成员名: 网号},
       "net_of": {(x,y): 网号},
       "bypassed": [(元件名, 网号)],  # 两端接在同一网 = 被短路
       "crossed_bodies": [(元件名, 交点)],   # 导线纵穿元件本体
       "components": [...]}

    成员名形如 "R1.t" / "Q1.c" / "VCC" / "GND" / "Vin"。
    没给 label 的元件用 "resistor@430,262" 这种坐标名, 仍可定位。
    """
    txt = open(svg_path, encoding="utf-8").read()
    lines, dots, comps, bad_lines = _extract_netlist(txt)

    # ---- 并查集 ----
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def key(p):
        return (round(p[0], 1), round(p[1], 1))

    # 每条线段建一个节点, 其两端点各自并进去
    for i, (x1, y1, x2, y2) in enumerate(lines):
        nid = ("seg", i)
        union(nid, ("pt", key((x1, y1))))
        union(nid, ("pt", key((x2, y2))))

    # 端点相接: 某线段的端点落在另一线段上 -> 连通
    for i, a in enumerate(lines):
        for j, b in enumerate(lines):
            if i == j:
                continue
            for p in ((b[0], b[1]), (b[2], b[3])):
                if _on_segment(p[0], p[1], *a):
                    union(("seg", i), ("pt", key(p)))

    # 交叉: 只有交点处有 junction 圆点才算连通
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            pt = _seg_cross(lines[i], lines[j])
            if not pt:
                continue
            if any(abs(pt[0] - dx) <= 2.5 and abs(pt[1] - dy) <= 2.5 for dx, dy in dots):
                union(("seg", i), ("seg", j))

    # 网络标签 marker: **相同编号 = 同一张网**。这是它存在的全部意义 ——
    # 跨功能块不想拉长导线时, 两端各画一个 ①, 它们就该电气相连。
    # 早先只在文档里这么写, 但 analyze() 完全不认(带 data-node 被跳过),
    # 于是按文档用 marker 连信号的图会被报"悬空", 或者更糟 ——
    # 图上以为连了、检查器认为没连, 两边都错。
    net_tags = {}
    for num, pt in _net_markers(txt):
        union(("nettag", num), ("pt", key(pt)))
        net_tags.setdefault(num, []).append(("pt", key(pt)))
        # 标签落在某条导线上时也要挂上去(通常是端点, 但支持中点)
        for i, s in enumerate(lines):
            if _on_segment(pt[0], pt[1], *s):
                union(("pt", key(pt)), ("seg", i))

    # 元件端子并到所在线段上
    members = {}
    for c in comps:
        base = c["kw"].get("label") or f'{c["sym"]}@{c["x"]:.0f},{c["y"]:.0f}'
        for tname, pt in c["terms"].items():
            # 电源/地符号本身就是网络名, 不挂在导线上也算一个节点
            if c["sym"] in ("vcc", "ground", "power_in"):
                nm = c["kw"].get("label") or ("GND" if c["sym"] == "ground" else "VCC")
                # 同一网络名(多个 +3.3V 符号)要合并
                union(("net", nm), ("pt", key(pt)))
                members.setdefault(nm, ("net", nm))
                # **不要 continue**: 电源符号也要挂到它所在的导线上。
                # 早先这里 continue 掉了, 于是"接在导线中点"的电源符号不会
                # 与该导线 union —— 只有当它正好落在某个**端点**上时, 才靠
                # 上面的端点合并步骤间接连上。后果: 中点接的地/电源被静默
                # 孤立, 而检查器报 0 问题。这是最危险的一类漏检。
                for i, s in enumerate(lines):
                    if _on_segment(pt[0], pt[1], *s):
                        union(("pt", key(pt)), ("seg", i))
                continue
            nm = f"{base}.{tname}"
            members[nm] = ("pt", key(pt))
            for i, s in enumerate(lines):
                if _on_segment(pt[0], pt[1], *s):
                    union(("pt", key(pt)), ("seg", i))

    # ---- 分组 ----
    nets = {}
    for nm, node in members.items():
        nets.setdefault(find(node), []).append(nm)
    # 网络标签也作为成员报出来, 网表里能看到 ① 在哪张网上
    for num, nodes in net_tags.items():
        nm = f"标签{num}"
        members[nm] = nodes[0]
        nets.setdefault(find(nodes[0]), []).append(nm)
    # 没有端子的孤立导线也算一张网(便于发现悬空线)
    for i in range(len(lines)):
        r = find(("seg", i))
        nets.setdefault(r, [])

    # ---- 检查 0: 落了单的网络标签 ----
    # 同号标签只有一个 = 它标了个什么也没连的东西。这几乎总是笔误:
    # 编号写错(① 对 ②)、或另一端忘了画。
    lonely_tags = sorted(n for n, nodes in net_tags.items()
                         if len(nodes) < 2)
    # ---- 检查 1: 电源与地同网 ----
    def root_of(nm):
        return find(members[nm]) if nm in members else None

    r_vcc = root_of("VCC") or root_of("+3.3V") or root_of("+5V")
    r_gnd = root_of("GND")
    shorted = bool(r_vcc is not None and r_vcc == r_gnd)

    # ---- 检查 2: 元件两端同网 = 被旁路 ----
    bypassed = []
    for c in comps:
        if c["sym"] in ("vcc", "ground", "power_in", "junction"):
            continue
        base = c["kw"].get("label") or f'{c["sym"]}@{c["x"]:.0f},{c["y"]:.0f}'
        names = [f"{base}.{t}" for t in c["terms"]]
        roots = {find(members[n]) for n in names if n in members}
        if len(names) >= 2 and len(roots) == 1 and names[0] in members:
            net = sorted(nets.get(next(iter(roots)), []))
            # 指出"哪条线不该存在": 两端各自所属的导线, 若重叠说明有根线横穿
            pts = [members[n] for n in names if n in members]
            hint = ""
            if c["body"]:
                bx0, by0, bx1, by1 = c["body"]
                for sg in lines:
                    if abs(sg[0] - sg[2]) < 0.6 and bx0 - .8 <= sg[0] <= bx1 + .8                        and min(sg[1], sg[3]) < by0 - .8 and max(sg[1], sg[3]) > by1 + .8:
                        hint = f" → 竖线 x={sg[0]:.0f} 纵穿本体, 改成从上下边缘起笔"
                        break
                    if abs(sg[1] - sg[3]) < 0.6 and by0 - .8 <= sg[1] <= by1 + .8                        and min(sg[0], sg[2]) < bx0 - .8 and max(sg[0], sg[2]) > bx1 + .8:
                        hint = f" → 横线 y={sg[1]:.0f} 纵穿本体, 改成从左右边缘起笔"
                        break
            if not hint:
                hint = " → 有一条线把两端连起来了, 顺着网表成员找它"
            bypassed.append((base, net, hint))

    # ---- 检查 3: 导线纵穿元件本体 ----
    crossed = []
    for c in comps:
        if not c["body"]:
            continue
        bx0, by0, bx1, by1 = c["body"]
        base = c["kw"].get("label") or f'{c["sym"]}@{c["x"]:.0f},{c["y"]:.0f}'
        for s in lines:
            x1, y1, x2, y2 = s
            if abs(x1 - x2) < 0.6:                  # 竖线
                if bx0 - 0.8 <= x1 <= bx1 + 0.8:
                    # 只有"整段穿过本体"才算旁路; 端点恰好贴在本体边上不算
                    if min(y1, y2) < by0 - 0.8 and max(y1, y2) > by1 + 0.8:
                        crossed.append((base, (x1, (by0 + by1) / 2),
                                        f" → 该竖线应止于 y={by0:.1f} 或从 y={by1:.1f} 起笔"))
            elif abs(y1 - y2) < 0.6:                # 横线
                if by0 - 0.8 <= y1 <= by1 + 0.8:
                    if min(x1, x2) < bx0 - 0.8 and max(x1, x2) > bx1 + 0.8:
                        crossed.append((base, ((bx0 + bx1) / 2, y1),
                                        f" → 该横线应止于 x={bx0:.1f} 或从 x={bx1:.1f} 起笔"))

    # ---- 检查 4: 端子悬空 ----
    # 元件的某个端子没有接到任何导线上。图上看是"引线差了一点点没接上",
    # 几像素的偏差肉眼根本看不出来, 但电路就是不通。
    # 本次实测抓到: 脚本把集电极竖线画在 XC=609, 而 npn() 的集电极在
    # cx+s=622 —— 差了 13px, 集电极整条悬空。
    dangling = []
    for c in comps:
        if c["sym"] in ("vcc", "ground", "power_in", "junction"):
            continue
        base = c["kw"].get("label") or f'{c["sym"]}@{c["x"]:.0f},{c["y"]:.0f}'
        for tname, pt in c["terms"].items():
            touch = sum(1 for s in lines if _on_segment(pt[0], pt[1], *s))
            # 两个元件端子直接对接(中间没有导线)也算接上
            if not touch:
                for other in comps:
                    if other is c:
                        continue
                    for opt in other["terms"].values():
                        if abs(opt[0] - pt[0]) < 1.2 and abs(opt[1] - pt[1]) < 1.2:
                            touch += 1
            if not touch:
                nearest, best = None, None
                for s in lines:
                    for e in ((s[0], s[1]), (s[2], s[3])):
                        dd = ((e[0] - pt[0]) ** 2 + (e[1] - pt[1]) ** 2) ** 0.5
                        if best is None or dd < best:
                            best, nearest = dd, e
                hint = ""
                if nearest is not None:
                    dx, dy = nearest[0] - pt[0], nearest[1] - pt[1]
                    if abs(dx) >= abs(dy):
                        hint = f" → 把该引线端点移到 x={nearest[0]:.1f} (差 {abs(dx):.1f}px)"
                    else:
                        hint = f" → 把该引线端点移到 y={nearest[1]:.1f} (差 {abs(dy):.1f}px)"
                dangling.append((f"{base}.{tname}", pt, best, nearest, hint))

    # ---- 检查 5: 声明过的"应该接在哪"没兑现 ----
    # 唯一能抓住"接到了错的节点上"的手段。接错节点时端子照样接上了导线,
    # 悬空/旁路/穿体全都不报 —— 只有把(实际网络)和(期望网络)比一次才发现。
    # 典型: 续流二极管该反并联在线圈两端, 结果阳极接到了基极行, D2 完全失效。
    miswired = []
    for spec in _custom_specs(txt):
        name = spec.get("name", "自绘元件")
        for tname, want in (spec.get("expect") or {}).items():
            mine = f"{name}.{tname}"
            if mine not in members:
                continue                     # 悬空已经在上一类报过了
            r_me = find(members[mine])
            # 期望目标支持三种写法, 见 declare() 的 expect 说明:
            #   1) (x, y) 坐标   —— 最稳, 不依赖任何命名
            #   2) 网络名        —— "+5V" / "GND"
            #   3) "元件名.端子名" —— 该元件必须带 label
            r_want, why = None, ""
            if isinstance(want, (list, tuple)) and len(want) == 2:
                k = ("pt", (round(want[0], 1), round(want[1], 1)))
                if k in parent:
                    r_want = find(k)
                else:
                    why = (f"坐标 {tuple(want)} 上没有导线或端子 —— "
                           f"检查这个点是否真的落在目标网络上")
            elif want in members:
                r_want = find(members[want])
            else:
                for nm, node in members.items():
                    if nm == want or nm.endswith("." + want):
                        r_want = find(node)
                        break
                if r_want is None:
                    # 区分"名字不存在"和"拼错了": 把可用的名字列出来
                    same = [nm for nm in members if nm.startswith(want.split(".")[0])]
                    if same:
                        why = f"没有 {want} 这个端子; 相近的有 {same[:4]}"
                    else:
                        why = (f"没有任何元件叫 {want.split('.')[0]} "
                               f"—— 内置符号不写 label 时无法用名字引用, "
                               f"改用坐标 expect={{'{tname}': (x, y)}}")
            if r_want is None:
                miswired.append((mine, want, None, why))
            elif r_me != r_want:
                actual = sorted(nets.get(r_me, []))
                miswired.append((mine, want, actual, ""))

    # 自绘符号的"飘端子": declare(terminals=...) 是**作者手填的绝对坐标**,
    # 与符号内部的绘制代码之间没有任何一致性约束 —— 内置符号有
    # measure_symbols.py 校准, 自绘符号没有。实测踩过: 继电器线圈声明端子
    # 跨 cx±38, 画弧的代码只跨 cx±21, 两个端子各悬在图形外 17px 的空白处。
    # 导线**确实**接到了声明的端点上(连通性完美), 但那里什么都没有 ——
    # 图上看到的是"线圈两端没接线", 而短路/旁路/穿体/悬空/接错全都不报。
    # 这是连通性检查的结构性盲区: 它比的是"端子之间通不通", 从不检查
    # "端子有没有画在图形上"。
    stray_terms = _dangling_custom_terms(txt)

    res = {"vcc_gnd_shorted": shorted,
           "nets": {k: sorted(v) for k, v in nets.items()},
           "members": {n: find(x) for n, x in members.items()},
           "bypassed": bypassed,
           "crossed_bodies": crossed,
           "dangling": dangling,
           "miswired": miswired,
           "malformed_lines": bad_lines,
           "stray_terms": stray_terms,
           "lonely_tags": lonely_tags,
           "components": comps,
           "n_lines": len(lines), "n_dots": len(dots)}

    if not quiet:
        print(f"== 网表分析 {svg_path}: {len(lines)} 条导线, {len(dots)} 个结点, "
              f"{len(comps)} 个元件 ==")
        if bad_lines:
            print(f"  [畸形] {len(bad_lines)} 条 <line> 的坐标不是数字, "
                  f"已被静默丢弃 —— 下面的问题多半是它的连锁反应:")
            for b in bad_lines[:3]:
                print(f"          {b}")
            if len(bad_lines) > 3:
                print(f"          ... 另有 {len(bad_lines) - 3} 条")
        if shorted:
            print("  [短路] VCC 与 GND 落在同一张网！")
        for base, net, hint in bypassed:
            print(f"  [旁路] {base} 两端接在同一张网 —— 该元件形同不存在{hint}")
        for base, pt, hint in crossed:
            print(f"  [穿体] 导线纵穿 {base} 本体 @ ({pt[0]:.0f},{pt[1]:.0f}) "
                  f"—— 该元件被旁路{hint}")
        for nm, pt, dd, near, hint in dangling:
            extra = "" if dd is None else f"（差 {dd:.1f}px）"
            print(f"  [悬空] {nm} @ ({pt[0]:.0f},{pt[1]:.0f}) 没接到任何导线{extra}{hint}")
        for nm, want, actual, why in miswired:
            if actual is None:
                print(f"  [接错] {nm} 声明应与 {want} 同网, 但 {why}")
            else:
                print(f"  [接错] {nm} 声明应与 {want} 同网, 实际却在 {actual}")
        for name, tn, pt, dd, ext in stray_terms:
            print(f"  [飘端子] {name}.{tn} @ ({pt[0]:.0f},{pt[1]:.0f}) 离本符号"
                  f"画出的图形 {dd:.1f}px（图形 x {ext[0]:.0f}..{ext[2]:.0f}, "
                  f"y {ext[1]:.0f}..{ext[3]:.0f}）—— 导线接在这个点上, "
                  f"但旁边没有图形, 图上看着像没接线")
        for num in lonely_tags:
            print(f"  [孤标签] 网络标签 「{num}」 只出现一次 —— 同号标签才相连, "
                  f"只有一个等于什么都没连（编号写错？或另一端忘了画？）")
        if not (shorted or bypassed or crossed or dangling or miswired
                or bad_lines or stray_terms or lonely_tags):
            print("  电气连通性: 无短路 / 无旁路 / 无穿体 / 无悬空端子 / 无接错 / "
                  "无畸形线段 / 无飘端子 / 无孤标签")
        print(f"  网络数: {len(nets)}")
        for r, ms in sorted(nets.items(), key=lambda kv: -len(kv[1])):
            if len(ms) >= 2:
                print(f"    {ms}")
    return res


# ============================ 器件符号 ============================
# 约定: 每个符号以 (cx, cy) 为中心, 沿水平轴放置。
#       dir=+1 电流/信号向 +x 方向, dir=-1 镜像。

def led(cx, cy, s=13, direction=1, label=None, color=LEDC):
    """
    发光二极管。direction=1: 阳极在左, 电流左->右。
                  direction=-1: 阳极在右(镜像)。
    s = 三角形半高。
    """
    out = []
    a = cx - s * direction          # 阳极尖角侧
    c = cx + s * direction          # 阴极横线侧
    out.append(polygon([(a, cy - s), (a, cy + s), (c, cy)], color))
    out.append(line(c, cy - s, c, cy + s, color, 2.5))
    # 两个发光箭头 (指向斜上/斜下外侧)
    for dy in (-1, 1):
        ax = cx + s * 0.2 * direction
        ay = cy + dy * s * 0.9
        bx = ax + s * 0.75 * direction
        by = ay + dy * s * 0.6
        out.append(line(ax, ay, bx, by, color, 1.2))
        out.append(polygon([(bx, by),
                            (bx - s * 0.25 * direction, by - dy * s * 0.15),
                            (bx - s * 0.05 * direction, by - dy * s * 0.32)], color))
    if label:
        out.append(text(cx, cy + s + 20, label, 11.5, "middle", color, "bold"))
    return _tag("".join(out), "led", cx, cy, s=s, direction=direction, label=label)


def resistor(cx, cy, w=42, h=15, label=None, vertical=False, color=RESC):
    """电阻(矩形, IEC 风格)。vertical=True 时竖放。"""
    out = []
    if vertical:
        out.append(rect(cx - h / 2, cy - w / 2, h, w, fill="#ffffff", stroke=color, sw=2))
        if label:
            out.append(text(cx + h / 2 + 6, cy + 4, label, 11, "start", color, "bold"))
    else:
        out.append(rect(cx - w / 2, cy - h / 2, w, h, fill="#ffffff", stroke=color, sw=2))
        if label:
            out.append(text(cx, cy - h / 2 - 8, label, 11, "middle", color, "bold"))
    return _tag("".join(out), "resistor", cx, cy, w=w, h=h, vertical=vertical, label=label)


def npn(cx, cy, s=17, label=None, flip=False):
    """
    NPN 三极管。c=集电极(上), e=发射极(下), b=基极(左)。
    flip=True 时基极在右(镜像)。
    s = 圆半径。
    返回 (svg, terminals) —— terminals 给出三个端子的坐标, 便于接线。
    """
    d = -1 if flip else 1
    out = [circle(cx, cy, s, fill="#f3e5f5", stroke=NPB, sw=2)]
    # 基极竖线(圆内靠基极侧)
    bx = cx - s * 0.35 * d
    out.append(line(bx, cy - s * 0.62, bx, cy + s * 0.62, NPB, 3))
    # 基极引线
    out.append(line(cx - s * d, cy, bx, cy, NPB, 2))
    # 集电极(上) 与 发射极(下): 从基极竖线斜向引出
    c_end = (cx + s * 0.55 * d, cy - s * 0.72)
    e_end = (cx + s * 0.55 * d, cy + s * 0.72)
    out.append(line(bx, cy - s * 0.30, c_end[0], c_end[1], NPB, 2))
    out.append(line(bx, cy + s * 0.30, e_end[0], e_end[1], NPB, 2))
    # 发射极箭头(指向外 = NPN)
    mx, my = (bx + e_end[0]) / 2, (cy + s * 0.30 + e_end[1]) / 2
    ang = math.atan2(e_end[1] - (cy + s * 0.30), e_end[0] - bx)
    for off in (0.55, -0.55):
        a2 = ang + math.pi + off
        out.append(line(mx, my, mx + 7 * math.cos(a2), my + 7 * math.sin(a2), NPB, 1.8))
    # 引出线到圆外
    out.append(line(c_end[0], c_end[1], cx + s * d, cy - s, NPB, 2))
    out.append(line(e_end[0], e_end[1], cx + s * d, cy + s, NPB, 2))
    if label:
        out.append(text(cx, cy - s - 8, label, 11.5, "middle", NPB, "bold"))
    terms = {
        "b": (cx - s * d, cy),            # 基极
        "c": (cx + s * d, cy - s),        # 集电极(上)
        "e": (cx + s * d, cy + s),        # 发射极(下)
    }
    return _tag("".join(out), "npn", cx, cy, s=s, flip=flip, label=label), terms


def push_button(cx, cy, w=44, h=30, label=None):
    """
    按键。水平两端为触点 A(左) / B(右)，各自向外引出。
    返回 (svg, (ax, ay, bx, by))。
    """
    out = [
        circle(cx - w / 2, cy, 3.2, fill=FG, stroke=FG),
        circle(cx + w / 2, cy, 3.2, fill=FG, stroke=FG),
        line(cx - w / 2, cy - h / 2, cx + w / 2, cy - h / 2, FG, 2.2),
        line(cx, cy - h / 2, cx, cy - h / 2 - 12, FG, 1.6),
    ]
    if label:
        out.append(text(cx, cy - h / 2 - 20, label, 12.5, "middle", FG, "bold"))
    return (_tag("".join(out), "push_button", cx, cy, w=w, h=h, label=label),
            (cx - w / 2, cy, cx + w / 2, cy))


def ground(x, y, size=13, label=None):
    """接地符号。接点在上, 向下画三横线。"""
    out = [line(x, y, x, y + size * 0.5, GNDC, 2)]
    for i, w in enumerate((size, size * 0.62, size * 0.28)):
        yy = y + size * 0.5 + i * size * 0.34
        out.append(line(x - w / 2, yy, x + w / 2, yy, GNDC, 2))
    if label:
        out.append(text(x, y + size * 0.5 + size * 1.4, label, 11, "middle", GNDC))
    return _tag("".join(out), "ground", x, y, size=size, label=label)


def pullup(x, y, to_y, label="10K", up_to="3V3"):
    """
    上拉/下拉电阻支路: 从节点 (x, y) 竖直走到 (x, to_y), 中间串一个电阻,
    末端接 up_to 电源。用于开漏输出、按键上拉、复位上拉等。
    返回 svg。
    """
    out = [junction(x, y)]
    mid = (y + to_y) / 2
    top = min(y, to_y)
    bot = max(y, to_y)
    out.append(line(x, y, x, mid - 22, WIRE, 2))
    out.append(resistor(x, mid, vertical=True, label=label))
    out.append(line(x, mid + 22, x, to_y, WIRE, 2))
    if to_y < y:
        out.append(vcc(x, to_y, up_to))
    else:
        out.append(ground(x, to_y))
    return _tag("".join(out), "pullup", x, y, to_y=to_y, label=label, up_to=up_to)


def vcc(x, y, label="3.3V", size=13):
    """电源符号(向上箭头)。接点在下方 (x, y)。"""
    out = [line(x, y, x, y - size, VC, 2)]
    out.append(polygon([(x, y - size - 6), (x - 5, y - size + 2), (x + 5, y - size + 2)], VC))
    out.append(text(x, y - size - 12, label, 12, "middle", VC, "bold"))
    return _tag("".join(out), "vcc", x, y, label=label)


def rgb_led(cx, cy, s=22, common_anode=True, label="RGB LED"):
    """
    RGB 三色灯珠(共阳/共阴)。三个阴极(或阳极)引脚在左侧, 公共端在右侧。
    返回 (svg, pins) —— pins = {"R":(x,y), "G":(x,y), "B":(x,y), "COM":(x,y)}
    """
    out = []
    r = s * 0.95
    out.append(circle(cx, cy, r, fill="#fff3e0", stroke="#ef6c00", sw=2))
    # 三个色点
    for dx, dy, col in ((-r * 0.3, -r * 0.32, "#e53935"),
                        (r * 0.03, r * 0.05, "#43a047"),
                        (r * 0.36, -r * 0.32, "#1e88e5")):
        out.append(circle(cx + dx, cy + dy, r * 0.20, fill=col, stroke=col))
    if label:
        out.append(text(cx, cy + r + 18, label, 12, "middle", "#ef6c00", "bold"))
    # 三个引线端子 (左侧, 竖直排列)
    pins = {}
    for i, name in enumerate(("R", "G", "B")):
        py = cy - s * 0.62 + i * s * 0.62
        out.append(line(cx - r, py, cx - r - 14, py, WIRE, 2))
        pins[name] = (cx - r - 14, py)
    # 公共端 (右侧)
    common_y = cy + (s * 0.62 if common_anode else s * 0.62)
    out.append(line(cx + r, common_y, cx + r + 14, common_y, WIRE, 2))
    pins["COM"] = (cx + r + 14, common_y)
    tag = "共阳" if common_anode else "共阴"
    out.append(text(cx + r + 18, common_y + 4, tag, 11, "start", DIM))
    return _tag("".join(out), "rgb_led", cx, cy, s=s, common_anode=common_anode, label=label), pins


# ---------- 全电路图附加符号 ----------

def crystal(cx, cy, w=34, h=16, label="8MHz"):
    """晶体谐振器: 两竖板 + 中间矩形。左右两端为引脚。"""
    out = [
        line(cx - w / 2, cy - h, cx - w / 2, cy + h, FG, 2.5),      # 左板
        line(cx + w / 2, cy - h, cx + w / 2, cy + h, FG, 2.5),      # 右板
        rect(cx - w * 0.28, cy - h * 0.62, w * 0.56, h * 1.24,
             fill="#ffffff", stroke=FG, sw=2),                       # 晶体体
    ]
    if label:
        out.append(text(cx, cy + h + 20, label, 11.5, "middle", FG, "bold"))
    return (_tag("".join(out), "crystal", cx, cy, w=w, h=h, label=label),
            ((cx - w / 2, cy), (cx + w / 2, cy)))


def capacitor(cx, cy, gap=7, plate=15, label=None, vertical=False):
    """无极性电容(两条平行板)。vertical=True 时竖放, 上板/下板。"""
    out = []
    if vertical:
        out.append(line(cx - plate, cy - gap, cx + plate, cy - gap, FG, 2.5))
        out.append(line(cx - plate, cy + gap, cx + plate, cy + gap, FG, 2.5))
        out.append(line(cx, cy - gap - 12, cx, cy - gap, WIRE, 2))
        out.append(line(cx, cy + gap, cx, cy + gap + 12, WIRE, 2))
        if label:
            out.append(text(cx + plate + 6, cy + 4, label, 11, "start", FG, "bold"))
    else:
        out.append(line(cx - gap, cy - plate, cx - gap, cy + plate, FG, 2.5))
        out.append(line(cx + gap, cy - plate, cx + gap, cy + plate, FG, 2.5))
        out.append(line(cx - gap - 12, cy, cx - gap, cy, WIRE, 2))
        out.append(line(cx + gap, cy, cx + gap + 12, cy, WIRE, 2))
        if label:
            out.append(text(cx, cy - plate - 8, label, 11, "middle", FG, "bold"))
    return _tag("".join(out), "capacitor", cx, cy, gap=gap, plate=plate,
                label=label, vertical=vertical)


def power_in(x, y, label="+5V", size=13):
    """
    电源输入端子(圆圈 + 标注)。接点在右侧 (x, y)。
    用于表示从外部电源/电池/USB 引入的电源。
    """
    out = [circle(x, y, 9, fill="#fff3e0", stroke=VC, sw=2.5),
           line(x + 9, y, x + 26, y, VC, 2.5),
           line(x, y - 5, x, y + 5, VC, 2)]
    out.append(text(x - 14, y + 5, label, 12.5, "end", VC, "bold"))
    return _tag("".join(out), "power_in", x, y, label=label)


def swd_header(x, y, w=110, h=90, label="SWD 调试口"):
    """
    4 线 SWD 调试排针(3V3 / SWDIO / SWCLK / GND)。
    返回 (svg, pins) —— pins = {"3V3":(x,y), "SWDIO":(x,y), "SWCLK":(x,y), "GND":(x,y)}
    """
    out = [rect(x, y, w, h, fill="#f5f5f5", stroke=FG, sw=2, rx=4),
           text(x + w / 2, y - 10, label, 11.5, "middle", FG, "bold")]
    names = ["3V3", "SWDIO", "SWCLK", "GND"]
    pins = {}
    for i, nm in enumerate(names):
        py = y + 18 + i * 18
        out.append(line(x + w, py, x + w + 16, py, WIRE, 2))
        out.append(text(x + w - 8, py + 4, nm, 10.5, "end", FG, "bold"))
        pins[nm] = (x + w + 16, py)
    return _tag("".join(out), "swd_header", x, y, w=w, h=h, label=label), pins


def reset_circuit(cx, cy, label="NRST"):
    """
    复位电路: NRST -> 10K 上拉到 3V3, 100nF 到 GND, 复位按键到 GND。
    以 (cx, cy) 为 NRST 节点。返回 (svg, node)
    """
    out = []
    out.append(junction(cx, cy))
    out.append(text(cx - 12, cy + 4, label, 11.5, "end", FG, "bold"))
    # 上拉电阻 (向上到 3V3)
    rx = cx + 70
    out.append(line(cx, cy, rx, cy, WIRE, 2))
    out.append(line(rx, cy, rx, cy - 30, WIRE, 2))
    out.append(resistor(rx, cy - 55, vertical=True, label="10K"))
    out.append(line(rx, cy - 80, rx, cy - 105, WIRE, 2))
    out.append(vcc(rx, cy - 105, "3V3"))
    # 电容到地
    out.append(line(cx, cy, cx, cy + 40, WIRE, 2))
    out.append(capacitor(cx, cy + 58, vertical=True, label="100nF"))
    out.append(line(cx, cy + 88, cx, cy + 106, WIRE, 2))
    out.append(ground(cx, cy + 106))
    return _tag("".join(out), "reset_circuit", cx, cy, label=label)


# ============================ 画布 ============================
class Box:
    """
    一组图元的包围盒累加器。用法:

        b = Box("驱动电路")
        b.add_item(svg_string, x0, y0, x1, y1, kind="元件")
        d.add(*b.parts, bounds=b)

    没有它的话, verify() 只能检查文字和线段之间的重叠 —— 看不出
    "两个器件画在了一起" 或 "某条支路超出画布右下角"。器件符号内部
    的几何是自洽的, 只有把它们的范围登记下来才能发现跨器件的碰撞。
    """

    def __init__(self, name="未命名"):
        self.name = name
        self.parts = []
        self.items = []            # [{kind,x0,y0,x1,y1,name}]

    def add_item(self, svg, x0, y0, x1, y1, kind="元件", name=None):
        if svg:
            self.parts.append(svg)
        self.items.append(_reg(kind, x0, y0, x1, y1, name or self.name))
        return self

    @property
    def bounds(self):
        if not self.items:
            return (0, 0, 0, 0)
        return (min(i["x0"] for i in self.items), min(i["y0"] for i in self.items),
                max(i["x1"] for i in self.items), max(i["y1"] for i in self.items))

    def __repr__(self):
        x0, y0, x1, y1 = self.bounds
        return f"<Box {self.name} {len(self.items)}项 {x0:.0f},{y0:.0f}..{x1:.0f},{y1:.0f}>"


class Doc:
    """一张接线图。用 add() 积累图元, save() 输出 SVG。"""

    def __init__(self, title, subtitle="", w=W, h=H):
        self.w, self.h = w, h
        self.boxes = []            # 器件包围盒, 供 verify() 做边界/碰撞检查
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="{BG}"/>',
            text(40, 46, title, 25, "start", FG, "bold"),
        ]
        if subtitle:
            self.parts.append(text(40, 74, subtitle, 14, "start", DIM))
        # 标题下的分隔线属于装饰, 打上 data-deco 让自检器跳过它,
        # 否则它离下面最近的一条导线总是很近, 会误报"水平线过近"。
        self.parts.append(
            f'<line{DECO} x1="40" y1="90" x2="{w - 40}" y2="90" '
            f'stroke="#cfd8dc" stroke-width="1.5"/>')

    def add(self, *svg, bounds=None, kind=None, name=None):
        """
        追加图元。bounds=(x0,y0,x1,y1) 时把该范围登记给自检器;
        也可直接传 bounds=Box 实例(取 .parts 和 .bounds)。

        不传 bounds 时, 若图元是带 data-sym 标记的符号(led/resistor/... ),
        会自动推算包围盒并登记 —— 所以老脚本不改一行也受越界/重叠检查保护。
        """
        if isinstance(bounds, Box):
            self.parts.extend(bounds.parts)
            self.boxes.extend(bounds.items)
            return self
        # 有些符号(npn/push_button/crystal/rgb_led/swd_header)返回 (svg, 端点)
        # 元组。直接 d.add(npn(...)) 是很自然的写法 —— 官方最小示例就是这么写的
        # —— 所以这里自动拆包取第 0 项, 而不是抛 TypeError。
        flat = []
        for s in svg:
            if isinstance(s, (tuple, list)):
                if not s:
                    continue
                s = s[0]                  # (svg, 端点) -> svg
            flat.append(s)
        for s in flat:
            if not s or not isinstance(s, str):
                continue
            self.parts.append(s)
            if bounds is None:
                auto = _auto_bounds(s)
                if auto:
                    got = _untag(s)
                    self.boxes.append(_reg(kind or got[0], *auto, name=name))
                elif kind or name:
                    # 传了 kind/name 但图元没带 data-sym 标记(自绘图元、
                    # 手写 SVG 片段): 不能把 kind 静默丢掉 —— 调用方以为
                    # 登记了, 实际没有, 越界/重叠检查会整体漏掉它。
                    raise ValueError(
                        "Doc.add(): 传了 kind/name 但无法自动推算包围盒 —— "
                        "该图元没有 data-sym 标记(不是内置符号)。"
                        "请显式给 bounds=(x0,y0,x1,y1)。")
        if bounds is not None and not isinstance(bounds, Box):
            self.boxes.append(_reg(kind or "图元", *bounds, name=name))
        return self

    def _canvas_rect(self, x, y, w, h, label="", fill="#fafafa",
                     stroke="#b0bec5", color="#546e7a"):
        """功能块外框。属于装饰 —— 不参与重叠与边界检查(它本来就要贴近画布边)。"""
        self.parts.append(
            f'<rect{DECO} x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.5" rx="8" stroke-dasharray="6 4"/>')
        if label:
            self.parts.append(
                f'<text{DECO} x="{x + 14}" y="{y + 24}" font-family="{FONT}" '
                f'font-size="14" fill="{color}" font-weight="bold">{esc(label)}</text>')
        return self

    # 中文别名, 便于脚本里读起来像在描述电路
    block = _canvas_rect

    def wire(self, *pts, color=WIRE, w=2):
        """折线: wire((x1,y1),(x2,y2),(x3,y3)) 逐段画直线。"""
        for i in range(len(pts) - 1):
            self.parts.append(line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], color, w))
        return self

    def notebox(self, x, y, w, lines, title="要点：", style="info"):
        """
        说明框。lines = [(文本, 级别)] 级别: "h"标题 / "n"正文 / "d"灰色小字
        style: info(蓝) / warn(黄) / ok(绿)
        """
        bg, br, tc = {"info": (NOTE_BG, NOTE_BR, "#0d47a1"),
                      "warn": (WARN_BG, WARN_BR, "#e65100"),
                      "ok": (OK_BG, OK_BR, "#2e7d32")}[style]
        line_h = 28
        h = 46 + line_h * len(lines)
        self.parts.append(
            f'<rect{DECO} x="{x}" y="{y}" width="{w}" height="{h}" fill="{bg}" '
            f'stroke="{br}" stroke-width="1.5" rx="6"/>')
        if title:
            self.parts.append(text(x + 20, y + 30, title, 14, "start", tc, "bold"))
            off = 0
        else:
            off = -22
        for i, (s, lvl) in enumerate(lines):
            col = FG if lvl == "n" else (DIM if lvl == "d" else tc)
            self.parts.append(text(x + 20, y + 30 + off + line_h * (i + 1), s, 13, "start", col))
        # 说明框是文字区, 登记它的范围只用于边界检查(防止框体出画布)
        self.boxes.append(_reg("说明框", x, y, x + w, y + h, "说明框"))
        return self

    def save(self, path):
        """
        输出 SVG。路径是相对路径时, 以本脚本所在目录为基准 ——
        这样脚本无论从哪里调用, 产物都落在工程目录里, 不会散到 CWD。

        会自动 flush 掉 place() 登记的标注 —— 落位必须等整张图画完,
        这里正是那个时机。
        """
        import json
        import os
        flush(self)
        if not os.path.isabs(path):
            import inspect
            frame = inspect.stack()[-1]          # 最外层调用者 = 用户脚本
            base = os.path.dirname(os.path.abspath(frame.filename))
            path = os.path.join(base, path)
            del frame
        path = os.path.normpath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 把器件包围盒写进去, verify() 才能查越界和器件重叠。
        # <desc> 在浏览器里不渲染, 加了完全看不出区别。
        for b in self.boxes:
            rec = {"kind": b["kind"],
                   "x0": round(b["x0"], 1), "y0": round(b["y0"], 1),
                   "x1": round(b["x1"], 1), "y1": round(b["y1"], 1)}
            if b.get("name"):
                rec["name"] = b["name"]
            payload = json.dumps(rec, ensure_ascii=False).replace('"', "&quot;")
            self.parts.append(f'<desc data-box="{payload}"/>')
        self.parts.append("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(self.parts))
        print(f"已生成: {path}")
        return path


def mcu_block(x, y, w, h, mcu_name, pins_right=(), pins_left=(), sub="单片机",
              show_pin_names=True, label_above=True):
    """
    MCU 方框。pins_right/pins_left = [(引脚名, 相对 y)]。
    show_pin_names=False 时引脚名由调用方自行绘制(需更紧凑的排版时用)。

    label_above: True  = 引脚名画在引线【上方】(默认)。
                 False = 画在引线【右侧】—— 仅当调用方不会再往右拉线时才用,
                         否则标签会压在后续导线上(自检器会报"文字压横线")。
    返回 (svg, {引脚名: (引出端点 x,y)}) —— 端点在方框外侧, 便于继续接线。
    """
    out = [rect(x, y, w, h, fill="#eceff1", stroke="#263238", sw=2.5, rx=6),
           text(x + w / 2, y + 26, mcu_name, 15, "middle", "#263238", "bold"),
           text(x + w / 2, y + 46, sub, 12, "middle", DIM)]
    ends = {}
    STUB = 20
    for name, dy in pins_right:
        out.append(line(x + w, y + dy, x + w + STUB, y + dy, WIRE, 2))
        if show_pin_names:
            if label_above:
                # 放在引线上方居中, 与后续导线错开
                out.append(text(x + w + STUB / 2, y + dy - 7, name, 12, "middle", FG, "bold"))
            else:
                out.append(text(x + w + STUB + 6, y + dy + 4, name, 12.5, "start", FG, "bold"))
        ends[name] = (x + w + STUB, y + dy)
    for name, dy in pins_left:
        out.append(line(x, y + dy, x - STUB, y + dy, WIRE, 2))
        if show_pin_names:
            if label_above:
                out.append(text(x - STUB / 2, y + dy - 7, name, 12, "middle", FG, "bold"))
            else:
                out.append(text(x - STUB - 6, y + dy + 4, name, 12.5, "end", FG, "bold"))
        ends[name] = (x - STUB, y + dy)
    return _tag("".join(out), "mcu_block", x, y, w=w, h=h, name=mcu_name,
                pins_right=[list(p) for p in pins_right],
                pins_left=[list(p) for p in pins_left],
                show_pin_names=show_pin_names,
                label_above=label_above), ends


# ============================================================
# 自检: 排版问题检测 (文字重叠 / 文字压线 / 导线假交叉)
# ============================================================
# 用法:
#   from wirelib import verify
#   n = verify("out.svg")            # 打印问题, 返回问题数
#   n = verify("out.svg", quiet=True)  # 只返回数量
#
# 为什么需要: 手工排版的坐标很容易让文字互相压住、或让导线贴得太近
# 被误读成"连接"。渲染成 PNG 用眼睛看能发现大部分问题, 但这个检查器
# 能把"差几个像素"的情况也抓出来, 比肉眼可靠。

def _text_boxes(svg_text):
    """提取所有 <text> 的包围盒 (x0, y0, x1, y1, 内容, 字号)。"""
    import re
    out = []
    for m in re.finditer(
        r'<text((?![^>]*data-deco)[^>]*)x="([\d.]+)" y="([\d.]+)"[^>]*font-size="([\d.]+)"'
        r'[^>]*text-anchor="(\w+)"[^>]*>(.*?)</text>', svg_text):
        if "data-node" in m.group(1):
            continue                      # 网络标签节点: 故意压在线上
        x, y, sz, anc, t = (float(m.group(2)), float(m.group(3)),
                            float(m.group(4)), m.group(5), m.group(6))
        t = re.sub(r'&[a-z]+;', 'x', t)
        # CJK 按 1.0em 估宽, ASCII 按 0.55em
        w = sum(sz * (1.0 if ord(c) > 0x2E80 else 0.55) for c in t)
        x0 = x if anc == "start" else (x - w if anc == "end" else x - w / 2)
        # 纵向包围盒收紧到基线上方 0.72em / 下方 0.18em:
        # 引脚名常紧贴导线短段(如 "PA0" 挨着 20px 的引脚引线),
        # 用宽松的 0.8/0.25 会把这些正常排版误判成"文字压线"。
        out.append((x0, y - sz * 0.72, x0 + w, y + sz * 0.18, t, sz))
    return out


def _segments(svg_text):
    """提取所有 <line> 线段, 跳过带 data-deco 标记的装饰线。"""
    import re
    out = []
    for m in re.finditer(
        r'<line((?![^>]*data-deco)[^>]*?)x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)',
        svg_text):
        out.append(tuple(float(m.group(i)) for i in (2, 3, 4, 5)))
    return out


def _canvas_size(svg_text):
    """从 <svg width= height=> 读出画布尺寸, 用于边界检查。"""
    import re
    m = re.search(r'<svg[^>]*width="(\d+)"[^>]*height="(\d+)"', svg_text)
    return (int(m.group(1)), int(m.group(2))) if m else (W, H)


def _clip_runs(a0, a1, b0, b1):
    """两段区间的重叠长度(a 与 b 相交的部分)。无交集返回 0。"""
    return max(0.0, min(a1, b1) - max(a0, b0))


def _boxes(svg_text):
    """
    读出 SVG 里登记的器件包围盒。

    为什么要存进 SVG: Doc 对象在脚本里, 但 verify() 只拿到文件。把
    包围盒写成 <desc data-box> 注释节点, 检查和绘制一次完成, 不用
    让调用方维护两份状态。这些节点在浏览器里不显示, 完全无副作用。
    """
    import html
    import json
    import re
    out = []
    # JSON 里本身带引号(alt 的键值都是字符串), 所以不能用 [^"]* 去匹配 ——
    # 会在第一个引号处截断。改成匹配到 '"/>' 之前, 再反转义。
    for m in re.finditer(r'<desc data-box="(.*?)"\s*/>', svg_text, re.S):
        raw = html.unescape(m.group(1))
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
    return out


# ============================================================
# 标注自动落位
# ============================================================
# 为什么要有它: 元件数值/型号的标注, 写死偏移必然出事 —— 同一个偏移在
# R1 右边是空的(干净)、到 R4 就压在集电极引线上。试过"放本体正上方"
# "放左侧", 都只是把冲突换个地方。所以改成登记 + 整图统一落位。

def _taken(d):
    """收集当前已画的所有线段与文字框, 供落位判碰撞用。
    直接读 d.parts —— 手写一份坐标账本迟早与实际画出来的对不上。"""
    import re
    segs, texts = [], []
    for sv in d.parts:
        for m in re.finditer(r'<line((?:(?!data-deco)[^>])*?)'
                             r'x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)', sv):
            segs.append(tuple(float(m.group(i)) for i in (2, 3, 4, 5)))
        for m in re.finditer(r'<text((?:(?!data-deco)[^>])*)x="([\d.]+)" y="([\d.]+)"'
                             r'[^>]*font-size="([\d.]+)"[^>]*text-anchor="(\w+)"'
                             r'[^>]*>(.*?)</text>', sv):
            if "data-node" in m.group(1):
                continue
            x, y, sz, anc, t = (float(m.group(2)), float(m.group(3)),
                                float(m.group(4)), m.group(5), m.group(6))
            w = sum(sz * (1.0 if ord(c) > 0x2E80 else 0.55) for c in t)
            x0 = x if anc == "start" else (x - w if anc == "end" else x - w / 2)
            texts.append((x0, y - sz * 0.72, x0 + w, y + sz * 0.18))
    return segs, texts


def _rect_hits(x0, y0, x1, y1, segs, texts, pad=1.0):
    """一个矩形是否压到任一线段或任一已画文字。规则与 verify() 一致。"""
    for (a, b, c, e) in segs:
        if abs(a - c) < 0.6:                       # 竖线
            if min(a, c) - pad < x1 and max(a, c) + pad > x0 \
               and min(b, e) - pad < y1 and max(b, e) + pad > y0:
                return True
        elif abs(b - e) < 0.6:                     # 横线
            if min(b, e) - pad < y1 and max(b, e) + pad > y0 \
               and min(a, c) - pad < x1 and max(a, c) + pad > x0:
                return True
    for (tx0, ty0, tx1, ty1) in texts:
        if min(tx1, x1) - max(tx0, x0) > 1.5 and min(ty1, y1) - max(ty0, y0) > 1.5:
            return True
    return False


def chain(d, start, items, step=90, y=None, to_ground=False,
          ground_drop=48, prefer="right"):
    """
    **串联支路**: 从 start 起, 依次摆若干元件并用导线串起来。
    端点和间距全部由 `terminals()` 算, **调用方一个坐标都不用填**。

    这是本库最常见的结构 —— 引脚 → 电阻 → LED → GND、引脚 → 电阻 → 三极管基极、
    电源 → 负载 → 集电极…… 以前每处都要手算 `x0+110`、`rx+21`、`lx+13`
    这类偏移, 手算就必然出现"差 3px 没接上"。

    ::

        mcu_svg, ends = mcu_block(140, 160, 190, 260, "STM32F103C8T6",
                                  pins_right=[("PC13", 130)])
        d.add(mcu_svg)

        r = chain(d, ends["PC13"], [
            ("R", resistor, dict(w=42, h=15), "1K"),
            ("L", led,      dict(s=13, direction=1), "LED1"),
        ], to_ground=True)

    参数:
        start    起点 (x, y)。用 `mcu_block` 返回的端点, 不要手填。
        items    [(键, 符号函数, 参数dict, 标注文字), ...]
                 - 键: 放进返回值的名字, 便于后续引用该元件的端子
                 - 符号函数: `resistor` / `led` / `capacitor` / `npn` …
                 - 参数dict: 传给该函数的参数(不用给 cx/cy, 会自动算)
                 - 标注文字: 走 place() 自动落位; 给 None 就不标
        step     相邻元件之间的**净间距**(两端子之间), 不是中心距。默认 90。
        y        支路的 y。默认取 start[1]。
        to_ground  True 时末尾接一个接地符号(下探 ground_drop)。
        ground_drop  下探深度。

    返回 dict::

        {"ends":  {键: (x, y)},            # 各元件的右侧端子
         "terms": {键: {端子名: (x,y)}},    # 各元件的全部端子
         "last":  (x, y),                  # 支路末端
         "y":     y}

    端点全部取自符号自己的端子表, 所以 `analyze()` 一定认得它们 ——
    不可能出现"差几像素没接上"。
    """
    if y is None:
        y = start[1]
    cur = (start[0], y)
    out = {"ends": {}, "terms": {}, "y": y}

    for key, sym, kw, label in items:
        kw = dict(kw or {})
        sname = getattr(sym, "__name__", sym)      # terminals 按"名字"查
        probe = terminals(sname, 0, 0, **kw)
        if not probe:
            raise ValueError(f"chain(): {sname} 没有端子定义, 无法自动排布")
        xs = [p[0] for p in probe.values()]
        left, right = min(xs), max(xs)
        half = (right - left) / 2.0

        cx = cur[0] + step + half          # 中心: 净间距 + 半宽
        fn = sym if callable(sym) else globals().get(sym)
        if not callable(fn):
            raise ValueError(f"chain(): 不认识符号 {sym!r}")
        # 自绘符号在这里会被自动 declare() —— 否则内部几何会被当成导线
        t = _draw_part(d, fn, cx, y, kw, name=key)
        out["terms"][key] = t
        xl, xr = cx + left, cx + right
        if cur[0] != xl:
            d.add(line(cur[0], y, xl, y, WIRE, 2))
        out["ends"][key] = (xr, y)
        cur = (xr, y)

        if label:
            place(d, cx, y, label, prefer=prefer)

    if to_ground:
        gx, gy = cur[0], y + ground_drop
        d.add(line(gx, y, gx, gy, WIRE, 2))
        d.add(ground(gx, gy))
        out["last"] = (gx, gy)
    else:
        out["last"] = cur
    return out


def place(d, x, y, s, prefer="right", size=12, color="#0d47a1"):
    """
    登记一个**待落位**的标注。整图画完后由 flush() 统一找不压线、不压字的
    位置画出来。数值/型号标注一律用它，不要手填坐标。

    ::

        d.add(resistor(430, 262, vertical=True))
        place(d, 430, 262, "33K")        # 只登记
        ...                              # 继续画剩下的
        d.save("out.svg")                # save() 会自动 flush

    **必须在整张图画完之后才落位** —— 登记时该元件的下游导线往往还没画
    （比如 R2 到 GND 那段），那时做碰撞检测会漏判，挑出一个稍后被导线
    穿过的位置。`Doc.save()` 会自动 flush，所以正常用法下不用操心；
    只有在 save 之前就要读文字框时才需要手动调 `flush(d)`。

    prefer: "right"/"left" 只是候选顺序, 最终落点由碰撞检测决定。
    """
    if not hasattr(d, "_pending_labels"):
        d._pending_labels = []
    d._pending_labels.append((x, y, s, prefer, size, color))
    return d


def flush(d):
    """把 place() 登记的标注统一落位。save() 会自动调用。"""
    pend = getattr(d, "_pending_labels", None)
    if not pend:
        return d
    for (x, y, s, prefer, size, color) in pend:
        segs, texts = _taken(d)
        hw = sum(size * (1.0 if ord(c) > 0x2E80 else 0.55) for c in s)
        cands = [(x + 32, "start"), (x - 32, "end"),
                 (x + 62, "start"), (x - 62, "end"),
                 (x, "middle"),
                 (x + 92, "start"), (x - 92, "end"),
                 (x + 122, "start"), (x - 122, "end")]
        if prefer == "left":
            cands = [cands[1], cands[0], cands[3], cands[2]] + cands[4:]
        # 画布边界: 落点出画的候选位**直接跳过**。否则 place() 会挑一个
        # 图外位置(实测: prefer="left" 时把注释放到 x=58, 而画布左边距是 40,
        # 整条注释被裁掉), 而且因为没压线/没压字, 它以为挑到了好位置。
        lim_x0, lim_y0 = 8, 8
        lim_x1, lim_y1 = getattr(d, "w", 1180) - 8, getattr(d, "h", 820) - 8
        placed = False
        for ax, anc in cands:
            x0 = ax if anc == "start" else (ax - hw if anc == "end" else ax - hw / 2)
            if x0 < lim_x0 or x0 + hw > lim_x1:
                continue
            if not _rect_hits(x0, y - 9, x0 + hw, y + 3, segs, texts):
                d.add(text(ax, y + 4, s, size, anc, color, "bold"))
                placed = True
                break
        if not placed:
            # 左右都满了(比如该元件整行都是导线): 退到本体下方。
            # 但**下方也可能已经站了别的标注**, 所以这里仍要逐个下移试 ——
            # 早先直接写死 y+40, 结果同一个位置放多个标注时会全部叠在一点。
            for k in range(1, 14):
                cy = y + 40 * k
                if cy + 3 > lim_y1:
                    break
                if not _rect_hits(x - hw / 2, cy - 9, x + hw / 2, cy + 3, segs, texts):
                    d.add(text(x, cy + 4, s, size, "middle", color, "bold"))
                    placed = True
                    break
        if not placed:
            # 仍然放不下: 至少错开, 不要叠在一起。落点也要夹在画布内。
            cy = min(y + 40 + 16 * len(texts), lim_y1 - 4)
            cx = min(max(x, lim_x0 + hw / 2), lim_x1 - hw / 2)
            d.add(text(cx, cy, s, size, "middle", color, "bold"))
    d._pending_labels = []
    return d


def verify(path, quiet=False, min_h_gap=18, margin=8, strict_bounds=False):
    """
    检查一张 SVG 的排版问题, 返回问题条数 (0 = 干净)。

    检测五类问题:
      1. 文字互相重叠
      2. 文字压在导线上          (长线段才判, 短引脚引线是正常排版)
      3. 平行水平导线间距过近    (< min_h_gap), 会被误读成连接
      4. 器件/图元超出画布       (被裁掉 = 图上缺东西, 最容易被漏掉)
      5. 器件与器件/说明框重叠   (两个符号画在同一个位置)

    margin:       边界容忍, 图元最多压线 margin px 不算越界
    strict_bounds: True 时, 器件超出「可用区」(画布减四周留白) 也报问题。
                   留白规则: 上 100 (标题区), 左右下 40。
    """
    import itertools
    s = open(path, encoding="utf-8").read()
    tb = _text_boxes(s)
    segs = _segments(s)
    CW, CH = _canvas_size(s)
    problems = []

    # 1) 文字重叠
    for a, b in itertools.combinations(tb, 2):
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        if ox > 1.5 and oy > 1.5:
            if oy < 14:      # 多是同一行文字挤在一起, 横着拉开更自然
                problems.append(("文字重叠",
                                 f'{ox:.0f}x{oy:.0f}px  "{a[4][:24]}" <-> "{b[4][:24]}" '
                                 f"→ 左右分开 ≥{ox + 6:.0f}px"))
            else:
                problems.append(("文字重叠",
                                 f'{ox:.0f}x{oy:.0f}px  "{a[4][:24]}" <-> "{b[4][:24]}" '
                                 f"→ 上下分开 ≥{oy + 6:.0f}px"))

    # 2) 文字压线
    #    短引线段 (<40px) 与旁边的标签是正常排版(引脚名挨着引脚引线),
    #    只对"长导线横穿文字"报问题, 否则误报太多失去意义。
    for t in tb:
        for (x1, y1, x2, y2) in segs:
            seg_len = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if seg_len < 40:
                continue
            if abs(y1 - y2) < 0.6:                      # 横线
                if min(y1, y2) - 1 < t[3] and min(y1, y2) + 1 > t[1]:
                    L, R = min(x1, x2), max(x1, x2)
                    if min(R, t[2]) - max(L, t[0]) > 3:
                        problems.append(("文字压横线",
                                         f'y={y1:.0f}  "{t[4][:28]}" '
                                         f"→ 文字上移 {t[3] - y1 + 4:.0f}px "
                                         f"(或下移 {y1 - t[1] + 4:.0f}px)"))
            elif abs(x1 - x2) < 0.6:                    # 竖线
                if min(x1, x2) - 1 < t[2] and min(x1, x2) + 1 > t[0]:
                    T, B = min(y1, y2), max(y1, y2)
                    if min(B, t[3]) - max(T, t[1]) > 3:
                        problems.append(("文字压竖线",
                                         f'x={x1:.0f}  "{t[4][:28]}" '
                                         f"→ 文字左移 {t[2] - x1 + 4:.0f}px "
                                         f"(或右移 {x1 - t[0] + 4:.0f}px)"))

    # 3) 平行水平导线间距
    #    先按 (y, 起, 止) 去重: 一条线常被拆成多段, 段之间共线不算"过近"。
    seen = set()
    horiz = []
    for (x1, y1, x2, y2) in segs:
        if abs(y1 - y2) < 0.6 and abs(x2 - x1) > 60:
            key = (round(y1), round(min(x1, x2)), round(max(x1, x2)))
            if key not in seen:
                seen.add(key)
                horiz.append(key)
    horiz.sort()
    for i in range(len(horiz)):
        for j in range(i + 1, len(horiz)):
            y_a, la, ra = horiz[i]
            y_b, lb, rb = horiz[j]
            gap = y_b - y_a
            if gap >= min_h_gap:
                break
            if gap == 0:                                # 共线, 非"平行过近"
                continue
            if min(ra, rb) - max(la, lb) > 30:          # 水平投影有重叠
                problems.append(("水平线过近",
                                 f"y={y_a} 与 y={y_b} 间距仅 {gap}px "
                                 f"→ 拉开到 ≥{min_h_gap}px"
                                 f"（把 y={y_b} 那组下移 {min_h_gap - gap}px）"))

    # 3b) 平行**竖直**导线间距
    #     与 3) 同理: 两条挨得很近的竖线也会被误读成一个连接点。
    #     早先只查水平线, 竖排的母线/通道过近一直漏检。
    seenv = set()
    vert = []
    for (x1, y1, x2, y2) in segs:
        if abs(x1 - x2) < 0.6 and abs(y2 - y1) > 60:
            key = (round(x1), round(min(y1, y2)), round(max(y1, y2)))
            if key not in seenv:
                seenv.add(key)
                vert.append(key)
    vert.sort()
    for i in range(len(vert)):
        for j in range(i + 1, len(vert)):
            x_a, va0, va1 = vert[i]
            x_b, vb0, vb1 = vert[j]
            gap = x_b - x_a
            if gap >= min_h_gap:
                break
            if gap == 0:                                # 共线, 非"平行过近"
                continue
            if min(va1, vb1) - max(va0, vb0) > 30:      # 纵向投影有重叠
                problems.append(("竖直线过近",
                                 f"x={x_a} 与 x={x_b} 间距仅 {gap}px "
                                 f"→ 拉开到 ≥{min_h_gap}px"
                                 f"（把 x={x_b} 那组右移 {min_h_gap - gap}px）"))

    # 4) 器件 / 图元 超出画布
    #    这类问题在 PNG 上表现为"图被切掉一块", 但如果切的是空白边,
    #    肉眼很难注意到; 器件被切掉就会缺线缺字, 照着接就错了。
    lim = {"x0": margin, "y0": margin, "x1": CW - margin, "y1": CH - margin}
    if strict_bounds:
        lim = {"x0": 40, "y0": 100, "x1": CW - 40, "y1": CH - 40}
    for it in _boxes(s):
        x0, y0, x1, y1 = it["x0"], it["y0"], it["x1"], it["y1"]
        over = []
        if x0 < lim["x0"]:
            over.append(f'左越界 {lim["x0"] - x0:.0f}px')
        if y0 < lim["y0"]:
            over.append(f'上越界 {lim["y0"] - y0:.0f}px')
        if x1 > lim["x1"]:
            over.append(f'右越界 {x1 - lim["x1"]:.0f}px')
        if y1 > lim["y1"]:
            over.append(f'下越界 {y1 - lim["y1"]:.0f}px')
        if over:
            # 给出可执行的修法: 画布该加多少, 或元素该内移多少
            need_w = max(CW, x1 + lim["x0"]) if x1 > lim["x1"] else CW
            need_h = max(CH, y1 + lim["y0"]) if y1 > lim["y1"] else CH
            if need_w != CW or need_h != CH:
                hint = f"→ 画布改成 w={need_w:.0f}, h={need_h:.0f}"
            else:
                hint = (f"→ 或把该元素内移 "
                        f"x+{max(0, lim['x0'] - x0):.0f} "
                        f"y+{max(0, lim['y0'] - y0):.0f}")
            problems.append(("超出画布",
                             f'{len(over)}处 {"/".join(over)}  '
                             f'{x0:.0f},{y0:.0f}..{x1:.0f},{y1:.0f}  '
                             f'(画布 {CW}x{CH})  {hint}'))

    # 4b) **纯文字** 超出画布
    #     第 4) 类只查登记过的器件/说明框。裸 <text>(手写的注释、标注、
    #     型号说明)没有包围盒登记, 跑到画布外会被渲染器直接裁掉 ——
    #     图上少半句注释, 而画布边上裁掉一块肉眼看不出来。
    for t in tb:
        tx0, ty0, tx1, ty1 = t[0], t[1], t[2], t[3]
        tover = []
        if tx0 < lim["x0"]:
            tover.append(f'左越界 {lim["x0"] - tx0:.0f}px')
        if ty0 < lim["y0"]:
            tover.append(f'上越界 {lim["y0"] - ty0:.0f}px')
        if tx1 > lim["x1"]:
            tover.append(f'右越界 {tx1 - lim["x1"]:.0f}px')
        if ty1 > lim["y1"]:
            tover.append(f'下越界 {ty1 - lim["y1"]:.0f}px')
        if tover:
            need_w = max(CW, tx1 + lim["x0"]) if tx1 > lim["x1"] else CW
            need_h = max(CH, ty1 + lim["y0"]) if ty1 > lim["y1"] else CH
            if need_w != CW or need_h != CH:
                thint = f"→ 画布改成 w={need_w:.0f}, h={need_h:.0f}"
            else:
                thint = (f"→ 或把该文字内移 "
                         f"x+{max(0, lim['x0'] - tx0):.0f} "
                         f"y+{max(0, lim['y0'] - ty0):.0f}")
            problems.append(("文字超出画布",
                             f'{len(tover)}处 {"/".join(tover)}  '
                             f'"{t[4][:24]}"  {thint}'))

    # 5) 器件与器件 / 说明框重叠
    #    跳过两轴都完美包含的情形(说明框套住元件是允许的嵌套)。
    items = _boxes(s)
    for i, j in itertools.combinations(range(len(items)), 2):
        a, b = items[i], items[j]
        ox = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
        oy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
        if ox <= 1.5 or oy <= 1.5:
            continue
        contained = ((a["x0"] >= b["x0"] and a["x1"] <= b["x1"] and
                      a["y0"] >= b["y0"] and a["y1"] <= b["y1"]) or
                     (b["x0"] >= a["x0"] and b["x1"] <= a["x1"] and
                      b["y0"] >= a["y0"] and b["y1"] <= a["y1"]))
        if contained:
            continue
        # 给出"至少挪开多少": 两轴中重叠较小的那条, 挪开它就分开了
        if ox <= oy:
            dx = ox + 8
            hint = (f"→ 水平分开 ≥{dx:.0f}px"
                    f"（把 [{a['kind']}] 左移到 x≤{a['x0'] - dx:.0f}, "
                    f"或把 [{b['kind']}] 右移到 x≥{b['x1'] + dx:.0f}）")
        else:
            dy = oy + 8
            hint = (f"→ 垂直分开 ≥{dy:.0f}px"
                    f"（把 [{a['kind']}] 上移到 y≤{a['y0'] - dy:.0f}, "
                    f"或把 [{b['kind']}] 下移到 y≥{b['y1'] + dy:.0f}）")
        problems.append(("器件重叠",
                         f'{ox:.0f}x{oy:.0f}px  [{a["kind"]}]{a.get("name") or ""} '
                         f'<-> [{b["kind"]}]{b.get("name") or ""}  {hint}'))

    if not quiet:
        print(f"== {path}: {len(tb)} 个文本, {len(segs)} 条线段, "
              f"{len(items)} 个登记图元, 画布 {CW}x{CH} ==")
        for kind, detail in problems:
            print(f"  [{kind}] {detail}")
        print("== 问题数:", len(problems), "==" if problems else "(无) ==")
    return len(problems)


def check_pins(project_dir, pins, verbose=True):
    """
    把图里用到的引脚名与工程配置对照一次, 返回问题列表。

    **为什么需要这个**: 引脚是这类图里唯一"写错会烧片子"的数据。
    `read_config()` 能从 `main.h`/`.ioc` 读出真实引脚, 但图里
    `mcu_block(pins_right=[("PA0", 60)])` 用的是**手写的字符串** ——
    两者之间没有任何校验。工程改过、或手抄时看错一行, 图上就是错的,
    而图看着完全正常(两道门也查不出: 引脚名只是一个字符串)。

    ::

        cfg = read_config("myproj")
        pins = [("PA0", 62), ("PA1", 100)]
        for w in check_pins("myproj", pins):
            print(w)          # 空列表 = 全对

    参数:
        project_dir  工程目录(交给 read_config)
        pins         `mcu_block` 的引脚表, 或纯引脚名列表 / 字典
                     支持 [("PA0", dy), ...] / ["PA0", ...] / {"PA0": ...}

    检查三类:
      1. **工程里配了这个引脚吗** —— 没配 = 图上画了源码里不存在的引脚
      2. **工程的标签指的是这个引脚吗** —— 图上标 `PA1 驱动 R`, 实际
         `LED_R` 在 `PA1` 吗? 引脚名与标签配错是最常见的手抄错误
      3. **有没有漏画** —— 工程里配了但图上没出现(仅提示, 不一定是错)
    """
    cfg = read_config(project_dir)
    known = {}          # 引脚名 -> [标签, ...]
    for label, val in (cfg.get("pins") or {}).items():
        pin = val[0] if isinstance(val, (tuple, list)) else val
        known.setdefault(str(pin), []).append(str(label))

    # 归一化传入的引脚表
    if isinstance(pins, dict):
        names = [str(k) for k in pins]
    else:
        names = []
        for it in (pins or ()):
            if isinstance(it, (tuple, list)):
                names.append(str(it[0]))
            else:
                names.append(str(it))

    out = []
    if not known:
        out.append(f"[引脚] 工程 {project_dir} 里没读到任何引脚配置"
                   f"（main.h 无 _Pin 宏、.ioc 也无 GPIO 配置）—— "
                   f"无法核对，请人工确认")
        return out

    for n in names:
        if n not in known:
            near = sorted(k for k in known if k[:2] == n[:2])
            hint = f"；同端口有 {near}" if near else ""
            out.append(f"[引脚] {n} 在工程里没有配置 —— 图上画了源码中"
                       f"不存在的引脚{hint}")
    for pin, labels in sorted(known.items()):
        if pin not in names:
            out.append(f"[引脚] 工程里的 {pin}（标签 {','.join(labels)}）"
                       f"没有出现在图里 —— 确认是有意省略")
    if verbose:
        for w in out:
            print("  " + w)
        if not out:
            print(f"  引脚核对通过: {len(names)} 个引脚与工程配置一致。")
    return out


# ============================================================
# 配置提取: 从工程源码读出引脚/时钟, 避免手抄出错
# ============================================================
# 用法:
#   cfg = read_config("myproj")
#   cfg["pins"]   -> {"LED_R": ("PA0", "GPIOA"), ...}
#   cfg["hse"]    -> 8000000
#
# 为什么要读源码而不是手填: 工程改了之后图不会自动跟着变,
# 手填的引脚表很容易过期。直接从 main.h / .ioc 读, 至少能保证
# 生成那一刻是准的。

def read_config(project_dir, verbose=False):
    """
    从 STM32 工程目录读取引脚与时钟配置。

    返回 dict:
      "pins"     {标签: (引脚, 端口)}  —— 标签来自 GPIO_Label; 无标签时用引脚名
      "pin_source" "main.h" | "ioc" | "none"  —— 引脚数据来自哪里
      "hse"      int | None
      "ioc"      {键: 值}
      "toolchain" str | None
      "warnings" [str]  —— 需要提醒调用方的问题

    两级回退:
      1) Core/Inc/main.h 的 XXX_Pin / XXX_GPIO_Port 宏 (CubeMX 生成, 带用户标签)
      2) .ioc 的 Pxx.Signal=GPIO_Output (+ Pxx.GPIO_Label, 若有)

    为什么需要回退: 有些工程的引脚在 CubeMX 里没设 User Label,
    main.h 里就【不会有】任何 _Pin 宏 —— 只读 main.h 会静默返回空字典,
    画图的人还以为工程没引脚。这种情况必须回到 .ioc 去读。
    """
    import os
    import re
    res = {"pins": {}, "pin_source": "none", "hse": None,
           "ioc": {}, "toolchain": None, "warnings": []}

    # ---- 1) main.h 的引脚宏 ----
    main_h = None
    for cand in ("Core/Inc/main.h", "Inc/main.h"):
        p = os.path.join(project_dir, cand)
        if os.path.exists(p):
            main_h = p
            break
    if main_h:
        txt = open(main_h, encoding="utf-8", errors="replace").read()
        pins = dict(re.findall(r"#define\s+(\w+)_Pin\s+GPIO_PIN_(\d+)", txt))
        ports = dict(re.findall(r"#define\s+(\w+)_GPIO_Port\s+(GPIO[A-E])", txt))
        for label, num in pins.items():
            port = ports.get(label)
            if port:
                # 统一成 "PA0" 形式 —— mcu_block 的引脚名也是这个写法,
                # 两处不一致的话调用方得写两套名字才能对上, 很容易 KeyError。
                res["pins"][label] = (port.replace("GPIO", "P") + num, port)
        if res["pins"]:
            res["pin_source"] = "main.h"

    # ---- 2) .ioc: 引脚 + 时钟 + 工具链 ----
    ioc_txt = None
    iocs = sorted(f for f in os.listdir(project_dir) if f.endswith(".ioc"))
    if iocs:
        ioc_txt = open(os.path.join(project_dir, iocs[0]),
                       encoding="utf-8", errors="replace").read()
        for k, v in re.findall(r"^(RCC\.\w+|ProjectManager\.\w+)=(.+)$", ioc_txt, re.M):
            res["ioc"][k] = v.strip()
        m = re.search(r"PLLMUL=RCC_PLL_MUL(\d+)", ioc_txt)
        if m and res["ioc"].get("RCC.PLLSourceVirtual", "").endswith("HSE"):
            res["hse"] = 72_000_000 // int(m.group(1))
        res["toolchain"] = res["ioc"].get("ProjectManager.TargetToolchain")

        # 若 main.h 没有引脚信息, 从 .ioc 兜底
        if not res["pins"]:
            # 引脚名可能带多个后缀: PA0-WKUP / PC13-TAMPER-RTC / PD0-OSC_IN
            # 所以用 (-[\w-]+)* 而不是只允许一个 -WORD。
            labels = {}
            for m in re.finditer(
                    r"^(P[A-E]\d+(?:-[\w-]+)*)\.GPIO_Label=(.+)$", ioc_txt, re.M):
                labels[m.group(1)] = m.group(2).strip()
            for m in re.finditer(r"^(P[A-E]\d+(?:-[\w-]+)*)\.Signal=(\w+)$",
                                 ioc_txt, re.M):
                raw_pin, sig = m.group(1), m.group(2)
                pin = raw_pin.split("-")[0]           # PA0-WKUP -> PA0
                port = "GPIO" + pin[1]
                tag = labels.get(raw_pin, pin)
                res["pins"][tag] = (pin, port)
            if res["pins"]:
                res["pin_source"] = "ioc"
                res["warnings"].append(
                    "main.h 里没有引脚宏(该工程未设 User Label), "
                    "引脚改从 .ioc 读取, 标签为引脚名或 .ioc 中的 GPIO_Label; "
                    "注意 .ioc 也会列出晶振/调试等固定功能脚")

    if not res["pins"]:
        res["warnings"].append(
            "没能从 main.h 或 .ioc 读到任何引脚 —— 请手工确认工程结构")

    # ---- 3) hal_conf.h 的 HSE_VALUE (最权威) ----
    for cand in ("Core/Inc/stm32f1xx_hal_conf.h", "Inc/stm32f1xx_hal_conf.h"):
        p = os.path.join(project_dir, cand)
        if os.path.exists(p):
            txt = open(p, encoding="utf-8", errors="replace").read()
            m = re.search(r"#define\s+HSE_VALUE\s+(\d+)", txt)
            if m:
                res["hse"] = int(m.group(1))
            break

    if verbose:
        print(f"引脚来源: {res['pin_source']}  ({len(res['pins'])} 个)")
        for k, v in res["pins"].items():
            print(f"  {k:12s} {v[0]}")
        print(f"HSE: {res['hse']}  |  工具链: {res['toolchain']}")
        for w in res["warnings"]:
            print("  ⚠ " + w)

    return res
