#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自检器回归测试 —— 确认 verify() 与 analyze() 该报的报、不该报的不报。

用法:
    python selftest.py

退出码 0 = 全部通过。

为什么要这个: 这两个检查器都是"减法"工具 —— 靠一堆阈值(线段最短长度、
水平线安全间距、文字包围盒的估算系数、端点容差)把正常情况排除掉,
只留下真问题。调这些阈值时最容易的失误是**顺手把真问题也排除掉了**,
而那样它们会一路返回 0, 看起来"图都干净了", 实际上什么都没查出来。

所以每个检查都配"必须报"和"不能报"两类用例。用例名前缀:
    A*  verify()  必须报      B*  verify()  不能报
    C*  analyze() 必须报      D*  analyze() 不能报
    （analyze 的问题数 = 短路+旁路+穿体+悬空+接错+畸形 六类之和）

改了 verify() / analyze() / _needs() / terminals() 之后跑一遍, 全都要过。

最后还会校验 references/quickref.md 与 wirelib.py 是否一致 —— 那一页是
"给 agent 看、不必读源码"的接口入口, 与实现漂移就会把人引到错误坐标上。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import find_root, fail_hint                     # noqa: E402
ROOT = find_root()
if not ROOT:
    print(fail_hint(), file=sys.stderr)
    sys.exit(2)
sys.path.insert(0, ROOT)

from wirelib import (Doc, Box, led, resistor, npn, vcc, ground,   # noqa: E402
                     push_button, junction, marker, text, verify,
                     capacitor, line, analyze, DECO, declare, WIRE,
                     place, flush, chain, mcu_block, register_symbol,
                     net2svg, bus_net, link,
                     crystal)


def cases(tmp):
    """返回 [(用例名, 期望问题数, 生成函数)]。"""
    out = []

    def mk(name, expect, fn, checker="verify"):
        out.append((name, expect, fn, checker))

    # ---------- A 系列: 必须报出来 ----------

    def a_canvas():
        d = Doc("越界", w=800, h=600)
        d.add(resistor(770, 570, label="R"),
              bounds=(740, 550, 810, 610), kind="元件", name="R")
        return d.save(os.path.join(tmp, "a_canvas.svg"))
    mk("A1 器件右下越界", 1, a_canvas)

    def a_canvas_left():
        d = Doc("越界", w=800, h=600)
        d.add(vcc(5, 300), bounds=(-30, 280, 20, 320), kind="电源")
        return d.save(os.path.join(tmp, "a_canvas_left.svg"))
    # 期望 2: 器件越界 1 + **它的 "3.3V" 标签也越界 1**。
    # 后者是新加的"纯文字越界"检查抓到的 —— vcc 放在 x=5, 标签向左右
    # 铺开后左缘到了 -16px。两处都是真问题(标签会被裁掉一段)。
    mk("A2 器件左侧越界", 2, a_canvas_left)

    def a_canvas_notebox():
        d = Doc("越界", w=800, h=600)
        d.notebox(600, 400, 400, [("① 说明框太宽", "n")])
        return d.save(os.path.join(tmp, "a_nb.svg"))
    mk("A3 说明框右越界", 1, a_canvas_notebox)

    def a_overlap():
        d = Doc("重叠", w=800, h=600)
        d.add(resistor(300, 300, label="R1"),
              bounds=(270, 285, 330, 315), kind="元件", name="R1")
        d.add(led(320, 302, label="LED1"),
              bounds=(290, 285, 350, 315), kind="元件", name="LED1")
        return d.save(os.path.join(tmp, "a_overlap.svg"))
    mk("A4 两个器件画在一起", 1, a_overlap)

    def a_overlap_auto():
        # 不传 bounds, 靠 data-sym 自动登记 —— 重叠同样要抓到。
        # 期望 2: 器件重叠 1 个 + 两行带标签的文字也被压住 1 个。
        d = Doc("重叠", w=800, h=600)
        d.add(led(400, 400, label="L1"))
        d.add(led(406, 402, label="L2"))
        return d.save(os.path.join(tmp, "a_overlap_auto.svg"))
    mk("A5 自动登记的器件重叠", 2, a_overlap_auto)

    def a_text():
        d = Doc("文字", w=800, h=600)
        d.add(text(400, 300, "重叠的文字", 14, "middle", "#000"))
        d.add(text(404, 302, "另一段文字", 14, "middle", "#000"))
        return d.save(os.path.join(tmp, "a_text.svg"))
    mk("A6 文字互相重叠", 1, a_text)

    def a_text_wire():
        d = Doc("压线", w=800, h=600)
        d.add(text(300, 302, "被横线穿过的长标签", 14, "start", "#000"))
        d.wire((100, 300), (700, 300))
        return d.save(os.path.join(tmp, "a_tw.svg"))
    mk("A7 文字被长导线穿过", 1, a_text_wire)

    def a_hgap():
        d = Doc("过近", w=800, h=600)
        d.wire((100, 300), (700, 300))
        d.wire((100, 310), (700, 310))
        return d.save(os.path.join(tmp, "a_hgap.svg"))
    mk("A8 平行水平线过近", 1, a_hgap)

    # ---------- B 系列: 不能报出来 ----------

    def b_clean():
        d = Doc("干净", w=800, h=600)
        b = Box("支路")
        b.add_item(led(300, 300, direction=1, label="LED1"),
                   270, 280, 330, 322)
        d.add(bounds=b)
        d.wire((100, 300), (270, 300))
        return d.save(os.path.join(tmp, "b_clean.svg"))
    mk("B1 正常单支路", 0, b_clean)

    def b_nested():
        # 说明框完全套住元件是允许的嵌套, 不算重叠。
        # notebox 高度 = 46 + 28*行数 —— 行数给够才能真正"包住",
        # 否则元件从框下缘探出去, 那是真重叠(说明框不是器件, 但会盖住它)。
        d = Doc("嵌套", w=800, h=600)
        d.add(led(300, 300, direction=1),
              bounds=(270, 280, 330, 322), kind="元件", name="LED")
        d.notebox(200, 230, 300, [("① 正常嵌套", "n"), ("② 第二行", "d")])
        return d.save(os.path.join(tmp, "b_nested.svg"))
    mk("B2 说明框正常套住元件", 0, b_nested)

    def b_adjacent():
        # 刚好留够间距的同构支路 —— 不能报
        d = Doc("相邻", w=800, h=760)
        for i in range(4):
            y = 200 + i * 80
            d.add(led(400, y, direction=1, label=f"LED{i + 1}"))
        return d.save(os.path.join(tmp, "b_adjacent.svg"))
    mk("B3 行距充足的同构支路", 0, b_adjacent)

    def b_short_stub():
        # 引脚名紧贴 20px 引线是正常排版, 不该报"文字压线"
        out = []
        out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">')
        out.append('<line x1="200" y1="150" x2="220" y2="150" '
                   'stroke="#37474f" stroke-width="2"/>')
        out.append('<text x="210" y="143" font-family="sans-serif" font-size="12" '
                   'fill="#1a1a1a" text-anchor="middle">PA0</text>')
        out.append('<rect width="400" height="300" fill="none"/></svg>')
        p = os.path.join(tmp, "b_stub.svg")
        open(p, "w", encoding="utf-8").write("".join(out))
        return p
    mk("B4 引脚名贴着短引线", 0, b_short_stub)

    def b_marker():
        # 网络标签故意画在导线端点上, 不该报
        d = Doc("标签", w=800, h=600)
        d.wire((200, 300), (600, 300))
        d.add(marker(600, 300, 1))
        d.add(marker(200, 300, 1))
        return d.save(os.path.join(tmp, "b_marker.svg"))
    mk("B5 网络标签落在导线端点", 0, b_marker)

    def b_collinear():
        # 共线的多段线是同一根导线, 不算"平行过近"
        d = Doc("共线", w=800, h=600)
        d.wire((100, 300), (400, 300))
        d.wire((400, 300), (700, 300))
        return d.save(os.path.join(tmp, "b_collinear.svg"))
    mk("B6 共线分段不误报", 0, b_collinear)

    def b_blank():
        d = Doc("空图", "只有标题", w=800, h=600)
        return d.save(os.path.join(tmp, "b_blank.svg"))
    mk("B7 只有标题的空图", 0, b_blank)

    def a_label_hits_wire():
        """手填偏移把标注写在导线上 —— 必须报(这正是 place() 要解决的问题)。"""
        d = Doc("标注压线", w=800, h=600)
        d.add(line(200, 100, 200, 500))
        d.add(text(200, 300, "33K", 12, "start", "#000"))
        return d.save(os.path.join(tmp, "a_lbl.svg"))
    mk("A9 手填偏移导致标注压线", 1, a_label_hits_wire)

    def b_place_avoids():
        """place() 登记后自动落位 —— 同样场景不该报。"""
        d = Doc("自动落位", w=800, h=600)
        d.add(line(200, 100, 200, 500))
        d.add(line(232, 100, 232, 500))     # 右侧 +32 处也有竖线, 必须再让开
        place(d, 200, 300, "33K")
        return d.save(os.path.join(tmp, "b_place.svg"))
    mk("B8 place() 自动避开导线", 0, b_place_avoids)

    def b_place_stack():
        """同一位置放多个 place() 标注 —— 必须错开, 不能叠在一点。
        (早先左右候选全被占时, 兜底写死 y+40, 多个标注会全部叠上。)"""
        d = Doc("多标注", w=800, h=700)
        d.add(line(100, 300, 700, 300))      # 整行导线, 左右候选位全占
        for s_ in ("AA", "BB", "CC", "DD"):
            place(d, 300, 300, s_)
        return d.save(os.path.join(tmp, "b_stack.svg"))
    mk("B10 place() 多标注自动错开", 0, b_place_stack)

    def b_place_flush_manual():
        """手动 flush 也要生效(不依赖 save 的自动调用)。"""
        d = Doc("手动flush", w=800, h=600)
        d.add(line(200, 100, 200, 500))
        place(d, 200, 300, "33K")
        flush(d)
        segs, texts = 0, 0
        import re as _re
        # flush 之后文字应该已经落到 d.parts 里
        n = sum(len(_re.findall(r"<text", p)) for p in d.parts)
        return d.save(os.path.join(tmp, "b_flush.svg")) if n else None
    mk("B9 手动 flush() 生效", 0, b_place_flush_manual)

    # ---------- C 系列: 网表必须报出来 ----------
    # 这几条是本次会话的实战教训: 都是"排版满分、肉眼满分、电路全错"。

    def c_short():
        """电源与地之间一根裸导线 —— 一上电就烧。"""
        d = Doc("短路", w=800, h=600)
        d.add(vcc(300, 140, "+3.3V"))
        d.add(ground(300, 420))
        d.add(line(300, 140, 300, 420))
        d.add(line(300, 140, 700, 140))
        return d.save(os.path.join(tmp, "c_short.svg"))
    mk("C1 VCC 直连 GND（短路）", 1, c_short, "analyze")

    def c_bypass():
        """引线纵穿竖直电阻本体 —— 电阻形同不存在。"""
        d = Doc("旁路", w=800, h=600)
        d.add(vcc(300, 140, "+3.3V"))
        d.add(ground(300, 420))
        d.add(line(300, 140, 300, 300))
        d.add(resistor(300, 334, vertical=True, label="1.5K"))
        d.add(line(300, 300, 300, 420))       # 纵穿本体 313..355
        return d.save(os.path.join(tmp, "c_bypass.svg"))
    # 期望 3: 短路(电源经旁路线直通地) + 旁路(电阻两端同网) + 穿体,
    # 三条各自独立成立 —— 同一处缺陷会被不同角度报出来, 这是有意的。
    mk("C2 导线纵穿电阻本体（旁路）", 3, c_bypass, "analyze")

    def c_dangling():
        """端子差 13px 没接上 —— 图上完全看不出。"""
        d = Doc("悬空", w=900, h=600)
        # npn 的 c 端子在 cx+s = 622; 故意把引线画在 609
        d.add(line(609, 498, 609, 200))
        d.add(line(609, 200, 800, 200))
        d.add(vcc(800, 200, "+3.3V"))
        d.add(npn(600, 520, s=22, label="Q1")[0])
        d.add(line(578, 520, 400, 520))
        d.add(line(622, 542, 622, 600))
        d.add(line(622, 600, 800, 600))
        d.add(ground(800, 600))
        return d.save(os.path.join(tmp, "c_dangling.svg"))
    mk("C3 集电极悬空（差 13px）", 1, c_dangling, "analyze")

    # ---------- D 系列: 网表不能误报 ----------

    def d_plain_cross():
        """两条导线纯交叉、交点无 junction —— 不算连接。
        这是最容易做错的一条: 判成连接会凭空造出短路假阳性。"""
        d = Doc("交叉未连接", w=800, h=600)
        d.add(vcc(200, 200, "+3.3V"))
        d.add(line(200, 200, 600, 200))       # 电源横线
        d.add(line(400, 100, 400, 500))       # 另一根竖线, 穿过它
        d.add(ground(400, 500))
        return d.save(os.path.join(tmp, "d_cross.svg"))
    mk("D1 纯交叉不算连接", 0, d_plain_cross, "analyze")

    def d_junction_connects():
        """同样交叉, 但交点有 junction —— 这才算连接, 于是短路成立。"""
        d = Doc("交叉已连接", w=800, h=600)
        d.add(vcc(200, 200, "+3.3V"))
        d.add(line(200, 200, 600, 200))
        d.add(line(400, 100, 400, 500))
        d.add(junction(400, 200))             # 交点打点
        d.add(ground(400, 500))
        return d.save(os.path.join(tmp, "d_junction.svg"))
    mk("D2 有 junction 才算连接（应报短路）", 1, d_junction_connects, "analyze")

    def d_good_led():
        """正常的 LED 支路: 两端各接各的端子, 不能被判成旁路。"""
        d = Doc("正常 LED", w=900, h=600)
        d.add(vcc(800, 200, "+3.3V"))
        d.add(line(200, 200, 300, 200))
        d.add(resistor(321, 200, label="1K"))
        d.add(line(342, 200, 387, 200))       # 到 LED 阴极(400-13)
        d.add(led(400, 200, direction=1, label="LED1"))
        d.add(line(413, 200, 800, 200))       # 从阳极(400+13)起
        d.add(ground(200, 200 + 40))
        d.add(line(200, 200, 200, 240))
        return d.save(os.path.join(tmp, "d_led.svg"))
    mk("D3 正常 LED 支路不误报", 0, d_good_led, "analyze")

    def d_add_tuple():
        """d.add(npn(...)) 不能崩 —— 官方最小示例就是这种写法。
        (早先 Doc.add 对元组抛 TypeError, 直接把最自然的写法堵死了。)

        检查器用 "layout": 这里三个符号故意不接线, 悬空是正常的 ——
        本条只验"没崩"和"图元进得去"。"""
        d = Doc("元组", w=1000, h=700)
        d.add(npn(400, 300, label="Q1"))
        d.add(push_button(700, 300))
        d.add(crystal(400, 500))
        return d.save(os.path.join(tmp, "d_tuple.svg"))
    mk("D7 d.add(npn(...)) 元组自动拆包", 0, d_add_tuple, "layout")

    def d_net2svg_chain():
        """纯网表驱动的串联主干 —— 调用方一个坐标都不给, 两道门都要过。"""
        d = Doc("网表驱动", w=1400, h=560)
        parts = [("R1", "resistor", dict(w=42, h=15), "1K"),
                 ("C1", "capacitor", dict(gap=7, plate=15), "100nF"),
                 ("LED1", "led", dict(s=13, direction=1), "绿")]
        nets = [("+3.3V", ["R1.l"]),
                ("n1", ["R1.r", "C1.l"]),
                ("n2", ["C1.r", "LED1.a"]),
                ("GND", ["LED1.k"])]
        net2svg(d, nets, parts)
        return d.save(os.path.join(tmp, "d_n2s.svg"))
    mk("D9 net2svg 纯网表串联主干", 0, d_net2svg_chain, "both")

    def d_chain_custom():
        """自绘符号注册后能进 chain() —— 否则继电器/光敏管这类电路
        只能手算坐标, 正是"差几像素"的根源。"""
        def mydiode(cx, cy, s=13, **kw):
            a, k = cx - s, cx + s
            return (f'<polygon points="{a},{cy - s} {a},{cy + s} '
                    f'{k},{cy}" fill="#000"/>')
        register_symbol("mydiode",
                        terminals=lambda cx, cy, s=13, **kw:
                            {"a": (cx - s, cy), "k": (cx + s, cy)},
                        body=lambda cx, cy, s=13, **kw:
                            (cx - s, cy - s, cx + s, cy + s))
        d = Doc("自绘进chain", w=1100, h=500)
        chain(d, (100, 250), [
            ("R", resistor, dict(w=42, h=15), "1K"),
            ("D", mydiode,  dict(s=13), "D1"),
        ], to_ground=True)
        return d.save(os.path.join(tmp, "d_chain_custom.svg"))
    mk("D8 自绘符号可进 chain()", 0, d_chain_custom)

    def d_bus_net():
        """竖直母线 + 四向挂支路 —— 解决 net2svg 排不了的分支节点。
        关键: 元件本体绝不能压在母线上(母线会纵穿它 = 旁路)。"""
        d = Doc("bus", w=1100, h=900)
        bus_net(d, cx=500, y0=180, y1=760, label="A", branches=[
            ("D1", "up",   0.0,  "led",      dict(s=13, direction=1), "光敏"),
            ("R1", "down", 0.35, "resistor", dict(w=42, h=15), "10K"),
            ("RV", "down", 0.75, "resistor", dict(w=42, h=15), "10K"),
        ])
        # 支路的自由端各自引出, 免得报悬空
        return d.save(os.path.join(tmp, "d_bus.svg"))
    mk("D10 bus_net 三分支节点(本体不压母线)", 0, d_bus_net, "layout")

    def d_chain_ok():
        """chain() 串一条支路 —— 端点全由端子表算, 两道门都该过。"""
        d = Doc("chain", w=1180, h=660)
        svg, ends = mcu_block(140, 160, 190, 260, "STM32F103C8T6",
                              pins_right=[("PC13", 130)])
        d.add(svg)
        chain(d, ends["PC13"], [
            ("R", resistor, dict(w=42, h=15), "1K"),
            ("L", led,      dict(s=13, direction=1), "LED1"),
        ], to_ground=True)
        return d.save(os.path.join(tmp, "d_chain.svg"))
    mk("D6 chain() 串联支路(排版+电气都干净)", 0, d_chain_ok, "both")

    def c_malformed():
        """坐标不是数字的 <line> 会被静默丢弃 —— 必须显式报出来。
        这是真实踩过的坑: 变量遮蔽了颜色常量 WIRE。"""
        d = Doc("畸形线", w=800, h=600)
        d.add(resistor(400, 200, label="R1"))
        d.parts.append('<line x1="#37474f" y1="300" x2="400" y2="400" '
                       'stroke="#37474f" stroke-width="2"/>')
        return d.save(os.path.join(tmp, "c_malformed.svg"))
    # 期望 3: 1 条畸形线 + R1 两个端子因此悬空(2)。级联报告是有意的 ——
    # 畸形线排在输出最前面, 并说明"下面的问题多半是它的连锁反应"。
    mk("C6 畸形 <line> 必须报出来", 3, c_malformed, "analyze")

    def c_power_midwire():
        """接在导线**中点**的电源/地符号必须与导线连通。
        早先它只在落在"端点"上时才连通 —— 中点接的被静默孤立, 而检查器
        报 0 问题。这是最危险的一类漏检: 电源域看着接好了, 实际是断的。"""
        d = Doc("中点电源", w=800, h=600)
        d.add(line(200, 300, 600, 300))
        d.add(vcc(400, 300, "+3.3V"))       # 中点接电源
        d.add(ground(600, 300))             # 端点接地
        return d.save(os.path.join(tmp, "c_midwire.svg"))
    # 必须报短路(中点电源与端点地同网)
    mk("C8 中点接的电源符号必须连通(报短路)", 1, c_power_midwire, "analyze")

    def d_power_midwire_ok():
        """单纯中点接地(不短路) -> 不该报问题。"""
        d = Doc("中点地", w=800, h=600)
        d.add(line(200, 300, 600, 300))
        d.add(ground(400, 300))
        return d.save(os.path.join(tmp, "d_midwire.svg"))
    mk("D11 中点接地: 不算问题", 0, d_power_midwire_ok, "analyze")

    def d_custom_in_chain():
        """自绘符号经 chain() 排布后, analyze() 必须认得它(含名字)。
        chain/bus_net 原来只 d.add(svg), 自绘符号的内部几何会被当成导线,
        而且检查器看不见它。"""
        def mydiode(cx, cy, s=13, **kw):
            a, k = cx - s, cx + s
            return (f'<polygon points="{a},{cy - s} {a},{cy + s} '
                    f'{k},{cy}" fill="#000"/>')
        register_symbol("mydiode2",
                        terminals=lambda cx, cy, s=13, **kw:
                            {"a": (cx - s, cy), "k": (cx + s, cy)},
                        body=lambda cx, cy, s=13, **kw:
                            (cx - s, cy - s, cx + s, cy + s))
        d = Doc("自绘进chain", w=1100, h=500)
        chain(d, (100, 250), [("D1", mydiode, dict(s=13), "光敏")],
              to_ground=True)
        return d.save(os.path.join(tmp, "d_cic.svg"))
    mk("D12 自绘符号进 chain 后可见", 0, d_custom_in_chain, "analyze")

    def c_custom_dangling():
        """自绘器件声明了端子但没接线 —— 不声明的话检查器完全看不见它。"""
        d = Doc("自绘悬空", w=800, h=600)
        d.add(declare(line(300, 200, 300, 260, WIRE, 2), "M1自绘",
                      terminals={"a": (300, 200), "b": (300, 260)}))
        d.add(vcc(300, 150, "+3.3V"))
        d.add(ground(300, 400))
        d.add(line(300, 150, 300, 180))     # 只接到 180, 离 200 差 20px
        d.add(line(300, 300, 300, 400))     # b 端(260) 也没接上
        return d.save(os.path.join(tmp, "c_custom.svg"))
    mk("C4 自绘器件端子悬空", 2, c_custom_dangling, "analyze")

    def c_custom_miswired():
        """declare(expect=) 没兑现 —— 接错节点, 前四类全都不报。"""
        d = Doc("接错", w=800, h=600)
        d.add(vcc(200, 150, "+3.3V"))
        d.add(ground(200, 500))
        # 电阻 R1: 上端接电源, 下端接 ... 本该接 R2 下端, 故意接错到电源
        d.add(line(200, 150, 200, 200))
        d.add(resistor(200, 221, vertical=True))
        d.add(line(200, 242, 200, 500))            # 下端 -> 地(正确)
        # R2 下端应该与 R1 上端(电源)不同网, 这里声明它应接 R2 之外的东西
        d.add(resistor(500, 221, vertical=True, label="R2"))
        d.add(line(500, 150, 500, 200))            # R2 上端 -> 也接电源
        d.add(line(500, 150, 200, 150))            # 电源母线
        d.add(line(500, 242, 500, 500))            # R2 下端 -> 地
        # 声明 R2 上端应与 GND 同网 —— 实际在 +3.3V, 必须报接错
        d.add(declare("", "R2", terminals={"t": (500, 200), "b": (500, 242)},
                      expect={"t": "GND"}))
        return d.save(os.path.join(tmp, "c_miswired.svg"))
    mk("C5 declare(expect) 接错节点", 1, c_custom_miswired, "analyze")

    def c_expect_coord():
        """expect 用坐标定位目标网络 —— 不依赖目标元件有没有 label。
        (内置符号常不写 label, 这时只有坐标能用。)"""
        d = Doc("坐标expect", w=900, h=600)
        d.add(vcc(200, 120, "+3.3V"))
        d.add(line(200, 120, 200, 200))
        d.add(resistor(200, 221, vertical=True))          # 故意不给 label
        d.add(line(200, 242, 200, 400))
        d.add(ground(200, 400))
        d.add(line(400, 120, 400, 400))
        # M1.a 声明应落在 R1 上端(坐标 200,200 所在的网), 实际接在地(400,...)
        d.add(declare(line(400, 400, 400, 450, WIRE, 2), "M1",
                      terminals={"a": (400, 400)},
                      expect={"a": (200, 200)}))
        return d.save(os.path.join(tmp, "c_coord.svg"))
    mk("C7 expect 用坐标定位(不依赖 label)", 1, c_expect_coord, "analyze")

    def d_bus_net_up():
        """bus_net() 的 up 支路必须落在接入点上方 —— 且**端点精确落在引线上**。
        早先 up 分支写死 `cy = tap - 68` 而忘了减端子偏移, 元件整体偏离
        接入点, 越靠母线下方偏得越多。这里用一个非零比例(0.5)钉住它:
        比例一变, 写死的偏移就对不上, 而正确实现自动跟随。"""
        d = Doc("bus up", w=1100, h=900)
        r = bus_net(d, cx=500, y0=300, y1=800, label="A", branches=[
            ("D1", "up",   0.5, "led",      dict(s=13, direction=1), None),
            ("R1", "down", 0.0, "resistor", dict(w=42, h=15), None),
        ])
        # 接入点: up 在 300+500*0.5=550, 端子应在 550+68=618
        #          down 在 300,              端子应在 300-68=232
        a = r["terms"]["D1"]["a"]
        b = r["terms"]["R1"]["l"]
        if abs(a[1] - 618) > 1 or abs(b[1] - 232) > 1:
            raise AssertionError(f"up/down 支路落点不对: {a} {b}")
        return d.save(os.path.join(tmp, "d_bus_up.svg"))
    mk("D13 bus_net up 支路落点正确", 0, d_bus_net_up, "layout")

    def d_mcu_bounds():
        """mcu_block 的包围盒必须**跟着引脚表走**。
        早先无条件返回 (0,0,w+20,h+8), 只有引线宽度、没有引脚名余量 ——
        左右都挂引脚名的 MCU, 最外侧标签会落在登记框外, 排版门就漏检。
        这里断言: 左引脚时 x0 为负(而不是恒等于 0)。"""
        from wirelib import _needs
        n_left = _needs("mcu_block", w=190, h=260,
                        pins_left=[["PA0", 30]], show_pin_names=True,
                        label_above=True)
        n_plain = _needs("mcu_block", w=190, h=260)
        if n_left[0] >= 0:
            raise AssertionError(f"左引脚没有把包围盒向左扩: {n_left}")
        d = Doc("mcu bounds", w=1000, h=700)
        svg, ends = mcu_block(200, 150, 190, 260, "STM32F103C8T6",
                              pins_right=[("PA0", 60)],
                              pins_left=[("PB0", 60)])
        d.add(svg)
        return d.save(os.path.join(tmp, "d_mcu_b.svg"))
    mk("D14 mcu_block 包围盒含引脚名", 0, d_mcu_bounds, "layout")

    def d_stray_ok():
        """端子确实落在图形上 —— 不能报飘端子。
        (反向钉住 tol=6px 的阈值: 正常的自绘符号不该被误报。)"""
        d = Doc("端子贴图形", w=900, h=600)
        body = line(270, 300, 330, 300, "#ef6c00", 2)
        d.add(declare(body, "L1线圈",
                      terminals={"m": (270, 300), "n": (330, 300)},
                      body=(270, 300, 330, 300)))
        d.add(vcc(270, 200, "+5V"))
        d.add(line(270, 200, 270, 300))
        d.add(ground(330, 400))
        d.add(line(330, 300, 330, 400))
        return d.save(os.path.join(tmp, "d_strayok.svg"))
    mk("D15 端子贴在本体上不误报", 0, d_stray_ok, "analyze")

    def c_stray_term():
        """自绘符号声明的端子飘在自己画出的图形之外 —— 必须报。

        这是实测踩到的真事: 继电器线圈声明端子跨 cx±38, 但画弧的代码只跨
        cx±21, 两个端子各悬在图形外 17px。导线**确实**接上了声明的端点,
        连通性完美, 图上看着却是"线圈两端没接线"。
        短路/旁路/穿体/悬空/接错**全都不报** —— 只有这一类能抓。"""
        d = Doc("飘端子", w=900, h=600)
        # 图形只画在 cx±21, 却声明端子在 cx±38
        body = line(279, 300, 321, 300, "#ef6c00", 2)
        d.add(declare(body, "K1线圈",
                      terminals={"m": (262, 300), "n": (338, 300)},
                      body=(279, 300, 321, 300)))
        d.add(vcc(262, 200, "+5V"))
        d.add(line(262, 200, 262, 300))          # 接到声明的 m 端子
        d.add(ground(338, 400))
        d.add(line(338, 300, 338, 400))          # 接到声明的 n 端子
        return d.save(os.path.join(tmp, "c_stray.svg"))
    # 必须报 2 个飘端子(m 与 n 各一个)。连通性是好的 —— 这正是要害。
    mk("C9 自绘端子飘在图形之外", 2, c_stray_term, "analyze")

    def d_marker_connects():
        """同号 marker 必须**真正并网** —— 这是它的全部意义。
        早先文档说"同号表示相连", 但 analyze() 不认(data-node 被跳过),
        于是按文档用 marker 连信号的图会被报悬空, 或者图上以为连了、
        检查器认为没连。"""
        d = Doc("标签", w=1000, h=600)
        d.add(vcc(200, 200, "+3.3V"))
        d.add(line(200, 200, 300, 200))
        d.add(marker(300, 200, 1))
        d.add(ground(700, 400))
        d.add(line(700, 400, 700, 300))
        d.add(marker(700, 300, 1))          # 同号 -> 应并成一张网(短路)
        return d.save(os.path.join(tmp, "d_marker.svg"))
    mk("D16 同号 marker 真正并网", 1, d_marker_connects, "analyze")

    def c_lonely_tag():
        """落了单的网络标签 —— 必须报。只有一个 ① 等于什么都没连。"""
        d = Doc("孤标签", w=900, h=600)
        d.add(vcc(200, 200, "+3.3V"))
        d.add(line(200, 200, 300, 200))
        d.add(marker(300, 200, 5))
        return d.save(os.path.join(tmp, "c_lonetag.svg"))
    mk("C10 单个网络标签(孤标签)必须报", 1, c_lonely_tag, "analyze")

    def c_mcu_pin_dangling():
        """MCU 引脚悬空必须报 —— 早先 terminals('mcu_block') 返回 {}，
        电气门对每个 MCU 引脚都是瞎的, 这是最大的检查盲区。"""
        d = Doc("MCU引脚", w=1000, h=700)
        svg, ends = mcu_block(100, 150, 190, 260, "STM32F103C8T6",
                              pins_right=[("PA0", 60)])
        d.add(svg)
        # 故意从离端点 40px 的地方起笔 -> PA0 悬空
        d.add(line(320, 210, 600, 210))
        d.add(resistor(621, 210, label="1K"))
        d.add(line(642, 210, 800, 210))
        d.add(ground(800, 210))
        return d.save(os.path.join(tmp, "c_mcupin.svg"))
    mk("C11 MCU 引脚悬空必须报", 1, c_mcu_pin_dangling, "analyze")

    def d_mcu_pin_ok():
        """MCU 引脚用返回值接上 -> 不能报。"""
        d = Doc("MCU接对", w=1000, h=700)
        svg, ends = mcu_block(100, 150, 190, 260, "STM32F103C8T6",
                              pins_right=[("PA0", 60)])
        d.add(svg)
        d.add(line(ends["PA0"][0], ends["PA0"][1], 600, ends["PA0"][1]))
        d.add(resistor(621, ends["PA0"][1], label="1K"))
        d.add(line(642, ends["PA0"][1], 800, ends["PA0"][1]))
        d.add(ground(800, ends["PA0"][1]))
        return d.save(os.path.join(tmp, "d_mcuok.svg"))
    mk("D17 MCU 引脚用返回值接上不报", 0, d_mcu_pin_ok, "analyze")

    def a_text_out():
        """纯文字(无包围盒登记)超出画布 —— 会被渲染器裁掉, 必须报。"""
        d = Doc("文字越界", w=800, h=600)
        d.add(text(760, 300, "这句注释跑到画布外面去了", 14, "start", "#000"))
        return d.save(os.path.join(tmp, "a_textout.svg"))
    mk("A10 纯文字超出画布", 1, a_text_out)

    def a_vgap():
        """两条平行**竖直**导线过近 —— 同"水平线过近", 必须报。"""
        d = Doc("竖线过近", w=800, h=600)
        d.wire((300, 150), (300, 500))
        d.wire((310, 150), (310, 500))
        return d.save(os.path.join(tmp, "a_vgap.svg"))
    mk("A11 平行竖线过近", 1, a_vgap)

    def a_link_h_mismatch():
        """link(mode='h') 两端 y 不同 -> 必须明确报错, 不能画条歪线。"""
        d = Doc("link", w=800, h=600)
        try:
            link(d, (100, 100), (300, 200), mode="h")
        except ValueError:
            return d.save(os.path.join(tmp, "a_link.svg"))
        raise AssertionError("link(mode='h') 两端 y 不同时没有报错")
    mk("A12 link 纯水平但 y 不同应报错", 0, a_link_h_mismatch)

    def a_net2svg_branch():
        """net2svg 遇到分支节点 -> 必须明确报错并指向 bus_net,
        而不是画出来再留一片悬空端子。"""
        d = Doc("分支", w=1400, h=800)
        parts = [("R1", "resistor", dict(w=42, h=15), "1K"),
                 ("R2", "resistor", dict(w=42, h=15), "2K"),
                 ("R3", "resistor", dict(w=42, h=15), "3K")]
        try:
            net2svg(d, [("+3.3V", ["R1.l"]),
                        ("A", ["R1.r", "R2.r", "R3.r"]),
                        ("GND", ["R2.l", "R3.l"])], parts)
        except ValueError as e:
            if "bus_net" not in str(e):
                raise AssertionError(f"报错没指向 bus_net: {e}")
            return d.save(os.path.join(tmp, "a_n2sb.svg"))
        raise AssertionError("net2svg 对 3 路分支节点没有报错")
    mk("A13 net2svg 分支节点应报错并指向 bus_net", 0, a_net2svg_branch)

    def d_custom_ok():
        """自绘器件声明齐全且接对了 —— 不能报。"""
        d = Doc("自绘正常", w=800, h=600)
        d.add(vcc(300, 150, "+3.3V"))
        d.add(ground(300, 500))
        d.add(resistor(300, 221, vertical=True, label="R1"))
        d.add(line(300, 150, 300, 200))            # 电源 -> R1 上端(200)
        d.add(line(300, 242, 300, 380))            # R1 下端(242) -> 自绘器件
        d.add(declare(line(300, 380, 300, 440, WIRE, 2), "M1自绘",
                      terminals={"a": (300, 380), "b": (300, 440)},
                      body=(288, 380, 312, 440),
                      expect={"a": "R1.b", "b": "GND"}))
        d.add(line(300, 440, 300, 500))            # 自绘器件 -> 地
        return d.save(os.path.join(tmp, "d_custom_ok.svg"))
    mk("D5 自绘器件声明齐全且正确", 0, d_custom_ok, "analyze")

    def d_deco_ignored():
        """网格线(data-deco)不能被当成导线, 否则会凭空造出短路。"""
        d = Doc("带网格", w=800, h=600)
        d.add(vcc(200, 150, "+3.3V"))
        d.add(line(200, 150, 600, 150))
        d.add(line(600, 150, 600, 250))
        d.add(capacitor(600, 250, vertical=True, label="100nF"))
        d.add(line(600, 262, 600, 400))
        d.add(ground(600, 400))
        # 一条横穿整张图的装饰线
        d.add(f'<line{DECO} x1="40" y1="300" x2="760" y2="300" '
              f'stroke="#ccc" stroke-width="0.5"/>')
        return d.save(os.path.join(tmp, "d_deco.svg"))
    mk("D4 装饰线不参与连通性", 0, d_deco_ignored, "analyze")

    return out


def main():
    # save() 会打印"已生成: ...", 测试时不需要, 静音掉
    import io
    import contextlib
    tmp = tempfile.mkdtemp(prefix="wirelib_selftest_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            all_cases = cases(tmp)
        bad = 0
        for name, expect, fn, checker in all_cases:
            with contextlib.redirect_stdout(io.StringIO()):
                path = fn()
            if checker == "layout":
                got = verify(path, quiet=True)
            elif checker == "both":
                r = analyze(path, quiet=True)
                an = (int(r["vcc_gnd_shorted"]) + len(r["bypassed"])
                      + len(r["crossed_bodies"]) + len(r["dangling"])
                      + len(r.get("miswired", []))
                      + len(r.get("stray_terms", []))
                      + len(r.get("lonely_tags", []))
                      + len(r.get("malformed_lines", [])))
                got = verify(path, quiet=True) + an
            elif checker == "analyze":
                r = analyze(path, quiet=True)
                got = (int(r["vcc_gnd_shorted"]) + len(r["bypassed"])
                       + len(r["crossed_bodies"]) + len(r["dangling"])
                       + len(r.get("miswired", []))
                       + len(r.get("stray_terms", []))
                       + len(r.get("lonely_tags", []))
                       + len(r.get("malformed_lines", [])))
            else:
                got = verify(path, quiet=True)
            ok = (got == expect)
            bad += 0 if ok else 1
            tag = "PASS" if ok else f"FAIL 期望{expect} 实得{got}"
            print(f"  [{tag}] {name}")
        print()
        print(f"共 {len(all_cases)} 个用例, 失败 {bad} 个。")
        if bad:
            print("verify() / analyze() 的阈值可能被调坏了 —— "
                  "注意检查是不是把真问题也排除了。")
            return 1
        print("两个自检器行为符合预期。")
        print()

        # ---- 诊断信息必须带"怎么改" ----
        # 这一条不是为了正确性, 而是为了**速度**: 报错只说"哪儿错了",
        # agent 得自己想改法、再跑一遍; 带上建议它就能直接照做。
        import io as _io
        d = Doc("提示", w=800, h=600)
        d.add(line(100, 300, 700, 300))
        d.add(line(100, 310, 700, 310))
        d.add(text(400, 500, "甲", 14, "middle", "#000"))
        d.add(text(404, 502, "乙", 14, "middle", "#000"))
        with contextlib.redirect_stdout(_io.StringIO()):
            q = d.save(os.path.join(tmp, "_hint.svg"))
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                verify(q)
        out = buf.getvalue()
        misses = [k for k in ("→", "px") if k not in out]
        print("诊断建议检查:", "PASS (报告里带 → 与具体 px)" if not misses
              else f"FAIL 缺少 {misses}")
        if misses:
            bad += 1

        # ---- 接口速查页必须与代码一致 ----
        # 这一页是"给 agent 看、不必读源码"的入口, 一旦与实现漂移就会
        # 把人引到错误坐标上(上一版手写的端子数据就是这么出事的)。
        import subprocess
        gen = os.path.join(HERE, "gen_quickref.py")
        r = subprocess.run([sys.executable, gen, "--check"],
                           capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode:
            print("references/quickref.md 已过期 —— 重跑 gen_quickref.py")
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
