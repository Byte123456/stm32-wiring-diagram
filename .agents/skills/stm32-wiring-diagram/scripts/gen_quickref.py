#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成接口速查页 references/quickref.md —— 让 agent 不必读 wirelib.py 源码。

用法:
    python gen_quickref.py            # 写 references/quickref.md
    python gen_quickref.py --check    # 只校验磁盘上的文件是否与代码一致

**这页必须是生成的, 不能手抄。** 手抄的几何数据撑不过几轮修改 ——
本技能上一版就把 _needs() 的尺寸估错过, 让一排电阻整片误报
"器件重叠"。所以这里的每一个数字都是当场从 terminals() / _needs() /
body_box() 反射出来的, 并由 selftest.py 断言磁盘文件与代码一致。

改了任何符号的签名/几何之后, 重跑本脚本; 忘了重跑的话 selftest.py 会失败。
"""
import argparse
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "references", "quickref.md")


def find_wirelib():
    """逐级向上找含 wirelib.py 的目录（可用环境变量 WIRELIB_DIR 覆盖）。"""
    sys.path.insert(0, HERE)
    from _paths import find_root
    return find_root()


def fmt_box(b):
    """把 (x0,y0,x1,y1) 的相对包围盒写成紧凑形式。"""
    if b is None:
        return "—"
    return "(%g, %g, %g, %g)" % tuple(round(v, 2) for v in b)


# 探针参数里没有引脚表时, mcu_block 的端子无从得知 —— 但那**不影响**
# 表格: terminals() 返回空字典, fmt_terms 直接写 "—"。
# (早先这里有个 NO_TERMS 映射想覆盖这种情形, 但它从来没被执行到:
#  表格循环里 t 恒为 terminals(...) 的返回值, 非空即走正常分支。
#  删掉是因为它不是"兜底", 是让人以为有兜底的死配置。)


def fmt_terms(t, sym=None):
    """把端子字典写成 "a=(x, y)  k=(x, y)" —— 值来自实测坐标。"""
    if not t:
        return "—"
    parts = []
    for k, (x, y) in t.items():
        parts.append("%s=(%g, %g)" % (k, round(x, 2), round(y, 2)))
    return " / ".join(parts)


# 每个符号: (调用参数, 摆位说明)。参数用于实际调 terminals()/_needs()。
# 这里只声明"用什么参数去探", 探出来的值一律不手写。
PROBES = [
    ("led", dict(s=13, direction=1), "cx, cy",
     "发光二极管"),
    ("resistor", dict(w=42, h=15), "cx, cy",
     "电阻(横放)"),
    ("resistor", dict(w=42, h=15, vertical=True), "cx, cy",
     "电阻(竖放)"),
    ("capacitor", dict(gap=7, plate=15), "cx, cy",
     "电容(横放)"),
    ("capacitor", dict(gap=7, plate=15, vertical=True), "cx, cy",
     "电容(竖放)"),
    ("npn", dict(s=17), "cx, cy",
     "NPN 三极管"),
    ("push_button", dict(w=44, h=30), "cx, cy",
     "按键"),
    ("vcc", {}, "x, y",
     "电源箭头(接点在下方)"),
    ("ground", dict(size=13), "x, y",
     "接地(接点在上方)"),
    ("power_in", {}, "x, y",
     "电源输入端子(接点在右侧)"),
    ("crystal", dict(w=34, h=16), "cx, cy",
     "晶振"),
    ("junction", {}, "cx, cy",
     "导线连接点"),
    ("pullup", dict(to_y=-100), "x, y",
     "上拉支路(to_y 为顶端)"),
    ("rgb_led", dict(s=22), "cx, cy",
     "RGB 灯珠"),
    ("swd_header", dict(w=110, h=90), "x, y",
     "SWD 排针(左上角)"),
    ("reset_circuit", {}, "cx, cy",
     "复位电路(节点)"),
    ("mcu_block", dict(w=190, h=260), "x, y",
     "MCU 方框(左上角)"),
]


def build(w):
    """生成整份速查页文本。"""
    L = []
    A = L.append
    A("# wirelib 接口速查（自动生成，勿手改）")
    A("")
    A("> 本页由 `scripts/gen_quickref.py` 从 `wirelib.py` **反射生成**，")
    A("> 所有坐标与尺寸都是当场实测值。改了符号请重跑生成器；")
    A("> 忘了重跑时 `selftest.py` 会失败。")
    A("")
    A("**给 agent 的用法**：读这一页就够了，不必读 `wirelib.py`。")
    A("只有在要**新增/修改符号本身**、或需要调试内部实现时，才去看源码。")
    A("")
    A("---")
    A("")

    # ---------- 1. 最小可用示例 ----------
    A("## 1. 最小示例")
    A("")
    A("```python")
    A("import os, sys")
    A('# 把 wirelib.py 所在的仓库根目录加进来')
    A('sys.path.insert(0, r"<仓库根>")          # 含 wirelib.py 的那一层')
    A("from wirelib import *")
    A("")
    A('d = Doc("标题", "副标题", w=1180, h=820)')
    A("")
    A('mcu_svg, ends = mcu_block(90, 150, 190, 400, "STM32F103C8T6",')
    A('                          pins_right=[("PA0", 30)])')
    A("d.add(mcu_svg)")
    A("")
    A("# 串联支路一律用 chain() —— 摆位/间距/导线/接地下探全自动")
    A("chain(d, ends['PA0'], [")
    A('    ("R", resistor, dict(w=42, h=15), "1K"),')
    A('    ("L", led,      dict(s=13, direction=1), "LED1"),')
    A("], to_ground=True)")
    A("")
    A("# 数值/说明标注用 place() —— 不要自己写 text() 填坐标")
    A('place(d, 500, 180, "1K")')
    A("")
    A('d.save("out.svg")       # 自动 flush 标注; 相对路径以脚本所在目录为基准')
    A("```")
    A("")
    A("**四条硬规矩**（其余都是细节）：")
    A("")
    A("1. **串联支路**用 `chain()`，不要自己算 `x0+110`、`rx+21` 这类偏移。")
    A("2. **接线端点**来自 `terminals()` 或符号返回值，不手填。")
    A("3. **标注文字**用 `place()` 登记，不要 `text()` 填坐标 —— 手填必然压线。")
    A("4. **自绘器件**用 `declare()` 声明端子/本体/`expect`，否则检查器看不见它。")
    A("5. **两段支路之间**的连线用 `link(a, b)`，不要手写 `d.add(line(...))`。")
    A("")
    A("### 分支节点 `bus_net()` —— 一个节点接 3~4 个元件")
    A("")
    A("串联用 `chain()`, 但真实电路里更麻烦的是**分支节点**:")
    A("")
    A("```")
    A("分压点 A ── D1 / R1 / RV1      (3 路)")
    A("集电极  ── RLY / D2 / Q1.c      (3 路)")
    A("+5V 母线 ── RLY / D2 / R3       (3 路)")
    A("```")
    A("")
    A("`net2svg()` 把元件沿一条主干排开, **各网络落在元件之间** —— 所以")
    A("同一个网络上的多个元件会被摊开在两处, 这些节点的端子就接不上了。")
    A("**必须换结构: 一根竖直母线, 各支路从它上面沿指定方向引出去。**")
    A("")
    A("```python")
    A("bus_net(d, cx=400, y0=200, y1=700, label='A', branches=[")
    A("    # (键, 方向, 位置比, 符号, 参数, 标注)")
    A("    ('D1',  'up',   0.0,  'led',      dict(s=13, direction=1), '光敏'),")
    A("    ('R1',  'down', 0.35, 'resistor', dict(w=42, h=15), '10K'),")
    A("    ('RV',  'down', 0.75, 'resistor', dict(w=42, h=15), '10K'),")
    A("])")
    A("```")
    A("")
    A("- 方向只有四个: `up` / `down` / `left` / `right`; 位置比 0~1 决定挂在哪一高度。")
    A("- 返回 `{'ends': {键: 自由端坐标}, 'terms': {键: {端子: 坐标}}, 'net': [...]}`")
    A("  —— 用它接着往下接, 不要手填坐标。")
    A("")
    A("**两条硬约束(实测踩过)**:")
    A("")
    A("1. **元件本体绝不能压在母线上。** 母线是一条连续竖线, 任何骑在它上面的")
    A("   元件都会被纵穿 (= 旁路)。所以 `bus_net()` 一律把元件横放在母线侧面,")
    A("   用一段引线拐回来。你也别自己写「竖放电阻直接挂母线」。")
    A("2. **同一母线同侧挂多路时, 各路的引出线会共线。** 比如两路都从右端往下")
    A("   走地线, 上面那路的竖线必然穿过下面那路的本体 —— 上路的线要往更外侧")
    A("   绕, 别占下路的列。")
    A("")
    A("### 连线 `link()` —— 把两段支路接起来")
    A("")
    A("`chain()` / `bus_net()` 各管一段,**它们之间**的连线用 `link()` ——")
    A("只给两个端点, 拐弯自动算。**不要手写 `d.add(line(...))`**:")
    A("")
    A("```python")
    A("link(d, bus['ends']['R1'], ends['PA0'])        # 母线 -> MCU 引脚")
    A("link(d, (cx1, y1), (cx2, y2), mode='vh')      # 两条母线")
    A("link(d, a, b, junction_at='mid')              # T 型接头打 junction")
    A("```")
    A("")
    A("- `mode`: `'hv'` 先横后竖(默认) / `'vh'` 先竖后横 / `'h'` 只水平 /")
    A("  `'v'` 只垂直 / `'auto'`。`'h'`/`'v'` 在两端不对齐时**直接报错**, ")
    A("  不会画一条歪线。")
    A("- 两端点**用符号返回值 / `terminals()` 取**, 不要手填。")
    A("- 两端重合时不画线并提示(通常意味着坐标算错了)。")
    A("")
    A("### 串联支路 `chain()`")
    A("")
    A("引脚→电阻→LED→GND、电源→负载→集电极…… 这类结构全部用 `chain()`。")
    A("**端点和间距由 `terminals()` 算出来，不是填出来的** —— 所以")
    A("「线从元件本体上穿过去把它短路」这种错误在结构上就不可能发生")
    A("（手写版踩过：电阻的线接到 LED 阳极再横穿本体）。")
    A("")
    A("```python")
    A("r = chain(d, start=(x, y), items=[")
    A('    ("R", resistor, dict(w=42, h=15), "1K"),      # (键, 符号, 参数, 标注)')
    A('    ("L", led,      dict(s=13, direction=1), "LED1"),')
    A("], step=90,          # 相邻元件之间的净间距(两端子之间, 非中心距)")
    A("   to_ground=True,   # 末尾接地下探")
    A("   ground_drop=48)")
    A("")
    A('r["ends"]["L"]        # 该元件右侧端子 (x, y)')
    A('r["terms"]["L"]       # 该元件的全部端子 {名字: (x,y)}')
    A('r["last"]             # 支路末端')
    A("```")
    A("")
    A("- `start` 用 `mcu_block` 返回的端点，或上一个 `chain` 的返回值。")
    A("- 标注(第 4 项)走 `place()` 自动落位；给 `None` 就不标。")
    A("- 元件参数里**不要**给 `cx`/`cy`，会自动算。")
    A("- 连到**母线**的支路(`chain` 管不到那一段)自己补 `line()` + `junction()`；")
    A("  这正是将来 `bus()` 要做的。")
    A("")
    A("---")
    A("")

    # ---------- 2. 符号与端子 ----------
    A("## 2. 符号签名 · 端子 · 包围盒")
    A("")
    A("**端子** = 电气上该接线的地方（用 `terminals(sym, x, y, **kw)` 取）。")
    A("**包围盒** = 排版占位（含标签，宁大勿小），用于越界/重叠检查。")
    A("")
    A("摆放基准 `(cx, cy)` 或 `(x, y)` 见“摆位”列。")
    A("")
    A("| 器件 | 摆位基准 | 端子（相对基准） | 包围盒（相对基准） | 返回 |")
    A("|---|---|---|---|---|")
    for sym, kw, base, desc in PROBES:
        t = w.terminals(sym, 0, 0, **kw)
        n = w._needs(sym, **kw)
        # 返回类型
        ret = "svg"
        if sym in ("npn", "push_button", "crystal", "rgb_led", "swd_header",
                   "mcu_block"):
            ret = "`(svg, 端点)`"
        elif sym in ("led", "resistor", "capacitor", "vcc", "ground",
                     "power_in", "pullup", "reset_circuit", "junction"):
            ret = "svg"
        A("| `%s` | %s | %s | %s | %s |" % (desc, base, fmt_terms(t, sym),
                                            fmt_box(n), ret))
    A("")
    A("**只能横放的符号**（没有 `vertical` 参数）：`led` / `npn` / `push_button` / ")
    A("`crystal` / `rgb_led`。需要竖着画时，把整个支路旋转 90° 布局，而不是期待")
    A("这些符号能转 —— 它们的端子坐标是横放定义的。只有 `resistor` / `capacitor`")
    A("有 `vertical=True`。")
    A("")
    A("> `mcu_block` 的 `pins_right=[(名字, 相对y)]` 返回 `{名字: 端点}`；")
    A("> **端点 = 引线外侧**：右侧引脚在 `(x+w+20, y+相对y)`，左侧在 `(x-20, y+相对y)`；")
    A("> 但一律直接用返回值 `ends[引脚名]`，不要自己算 —— 引线长度（20px）是内部常量，")
    A("> 将来可能变。")
    A("> `npn` 返回 `(svg, {'b','c','e'})`；`push_button` 返回 `(svg, (ax,ay,bx,by))`；")
    A("> `crystal` 返回 `(svg, (左端, 右端))`；`rgb_led` / `swd_header` 返回 `(svg, {名字: 端点})`。")
    A("")
    A("### 完整签名")
    A("")
    A("```python")
    seen = set()
    for sym, _, _, _ in PROBES:
        if sym in seen:
            continue          # 横放/竖放两条探针共用一个签名
        seen.add(sym)
        A("%s%s" % (sym, inspect.signature(getattr(w, sym))))
    A("```")
    A("")
    A("---")
    A("")

    # ---------- 3. 画布 ----------
    A("## 3. 画布 `Doc`")
    A("")
    A("```python")
    A('d = Doc(title, subtitle="", w=1180, h=820)')
    A("d.add(*svgs)                     # 追加图元; None 会被忽略")
    A("d.add(svg, bounds=(x0,y0,x1,y1), kind='元件', name='Q1')   # 手动登记包围盒")
    A("d.wire((x1,y1), (x2,y2), ..., color=WIRE, w=2)   # 折线, 自动逐段描")
    A("d.notebox(x, y, w, [(文本, 级别)], title='要点：', style='info')")
    A("d.block(x, y, w, h, 'E. 驱动电路')    # 功能块外框(虚线圈出)")
    A("d.save('out.svg')                # 返回绝对路径")
    A("```")
    A("")
    A("- `notebox` 级别：`\"n\"` 正文 / `\"d\"` 次要小字 / `\"h\"` 标题色；")
    A("  `style`：`\"info\"`(蓝) / `\"warn\"`(黄) / `\"ok\"`(绿)。")
    A("  **高度 = 46 + 28×行数**，排完注意别超出画布。")
    A("- `d.save()` 传相对路径时，**基准是调用脚本所在目录**（不是 CWD），"
      "目录不存在会自动建。")
    A("- 元件包围盒**自动登记**：符号返回的 SVG 外层带 `data-sym` 标记，"
      "`add()` 认出来就按上表尺寸登记，所以一般不用手写 `bounds`。")
    A("")
    A("### 标注自动落位 `place()` —— 不要手填标注坐标")
    A("")
    A("元件数值/型号的标注，**写死偏移必然出事**：同一个偏移在 R1 右边是空的，")
    A("到 R4 就压在集电极引线上。用 `place()` 登记，整图画完后自动找干净位置：")
    A("")
    A("```python")
    A("d.add(resistor(430, 262, vertical=True))")
    A('place(d, 430, 262, "33K")        # 只登记, 不立刻画')
    A("...                              # 继续画剩下的走线")
    A('d.save("out.svg")                # save() 自动 flush, 不用手动调')
    A("```")
    A("")
    A("- 候选位按 `prefer`（`\"right\"`/`\"left\"`）的顺序逐个试，选第一个不压线、")
    A("  不压字的。四周都满了才退到本体下方。")
    A("- **必须整张图画完再落位** —— 登记时下游导线往往还没画，那时判碰撞会漏。")
    A("  `save()` 会在正确时机自动调 `flush()`，所以正常用法下不用管。")
    A("")
    A("### 自绘器件想让 `chain()` 也能排布：`register_symbol()`")
    A("")
    A("`chain()` 默认只认内置符号。自绘器件要先用 `register_symbol()` 注册")
    A("端子表和本体，之后就能像内置符号一样进 `chain()`：")
    A("")
    A("```python")
    A("def mydiode(cx, cy, s=13, **kw):")
    A('    """只画图形, **不画外接引线** —— 引线由调用方 d.wire() 画。"""')
    A("    return f'<polygon points=\"...\"/>'")
    A("")
    A('register_symbol("mydiode",')
    A("    terminals=lambda cx, cy, s=13, **kw: {'a': (cx-s, cy), 'k': (cx+s, cy)},")
    A("    body=lambda cx, cy, s=13, **kw: (cx-s, cy-s, cx+s, cy+s))")
    A("")
    A("chain(d, start, [")
    A('    ("R", resistor, dict(w=42, h=15), "1K"),')
    A('    ("D", mydiode,  dict(s=13), "D1"),        # 自绘符号也能串进来')
    A("], to_ground=True)")
    A("```")
    A("")
    A("**两条容易踩的**：")
    A("")
    A("1. **引线不要画在符号里。** 器件几何要交给 `declare()` 包进 `<g data-custom>`")
    A("   才会被检查器忽略；一旦包进去，画在里面的引线**也一起被忽略**，")
    A("   于是端子报悬空。所以引线一律由调用方 `d.wire()` 画到端子上。")
    A("2. **`declare()` 仍要照用。** 两者分工：`register_symbol` 管「能不能自动")
    A("   排布」，`declare` 管「这个实例的端子接对了没有」（含 `expect` 校验）。")
    A("")
    A("### 自绘器件必须 `declare()`")
    A("")
    A("`analyze()` 只认识上表里的内置符号。**你自己拼的器件（继电器线圈、触点、")
    A("续流管、光敏管、MOS、传感器模块……）它完全看不见** —— 不是「查了没问题」，")
    A("是「压根没看」，接错也能通过电气门。")
    A("")
    A("```python")
    A("from wirelib import declare")
    A("")
    A('d.add(declare(my_symbol_svg, "元件名",')
    A('              terminals={"端子名": (x, y), ...},   # 绝对坐标')
    A("              body=(x0, y0, x1, y1),             # 本体矩形, 拿不准可省")
    A('              expect={"端子名": (x, y)},            # 该端子应在的网络(推荐坐标)')
    A('              note="可选说明"))')
    A("```")
    A("")
    A("- `expect` 的目标写**目标网络上的任意一点** `(x, y)` 最稳 —— 不依赖目标元件")
    A("  有没有 label。也可写电源名（`+5V`）或 `元件名.端子名`（该元件必须带 label；")
    A("  内置符号常不写 label，这时只能用坐标）。")
    A("  接错节点时端子照样「接上了导线」，短路/旁路/穿体/悬空**全都不报**，")
    A("  只有 `expect` 能发现，报 `[接错] ...`。")
    A("- 没声明的自绘器件会被忽略（与从前行为一致），不会让既有脚本报错。")
    A("")
    A("---")
    A("")

    # ---------- 4. 两个检查器 ----------
    A("## 4. 两个检查器（交付前都要过）")
    A("")
    A("### 排版 `verify()` / `check_svg.py`")
    A("")
    A("```python")
    A("n = verify(path, quiet=False, min_h_gap=18, margin=8, strict_bounds=False)")
    A("```")
    A("")
    A("```bash")
    A("python .agents/skills/stm32-wiring-diagram/scripts/check_svg.py \"工程目录/*.svg\"")
    A("python .agents/skills/stm32-wiring-diagram/scripts/check_svg.py --png \"工程目录/*.svg\"")
    A("```")
    A("")
    A("**报告里直接带改法** —— 不用自己想「该挪多少」：")
    A("")
    A("```")
    A("[器件重叠] 40x30px  R1 <-> L1  → 垂直分开 ≥38px（把 R1 上移到 y≤247, 或把 L1 下移到 y≥353）")
    A("[超出画布] 右越界 18px          → 画布改成 w=818, h=618")
    A("[悬空] Q1.c 差 13.0px           → 把该引线端点移到 y=498.0")
    A("[旁路] 1.5K 两端同网            → 竖线 x=300 纵穿本体, 改成从上下边缘起笔")
    A("```")
    A("")
    A("查**七类**，返回 0 = 干净：")
    A("")
    A("1. 文字互相重叠　2. 文字压长导线")
    A("3. 平行水平线过近（< `min_h_gap`）　4. **平行竖线过近**（同理：")
    A("　 两条挨得近的竖线也会被误读成连接）")
    A("5. **器件超出画布**　6. **器件互相重叠**")
    A("7. **文字超出画布**（裸 `<text>` 没有包围盒登记，跑到画布外会被")
    A("　 渲染器直接裁掉 —— 图上少半句注释，肉眼看不出来）")
    A("")
    A("### 电气 `analyze()` / `check_net.py`")
    A("")
    A("```python")
    A("r = analyze(path, quiet=False)")
    A('r["vcc_gnd_shorted"]   # 电源与地同网')
    A('r["bypassed"]          # [(元件名, 网成员)]  两端同网')
    A('r["crossed_bodies"]    # [(元件名, 交点)]    导线纵穿本体')
    A('r["dangling"]          # [(端子名, 坐标, 距离, 最近端点)]')
    A('r["miswired"]          # [(端子名, 期望网络, 实际网络)]  自绘器件接错节点')
    A('r["stray_terms"]       # [(元件名, 端子名, 坐标, 距离, 图形极值)]')
    A('                       #   自绘端子飘在自己画出的图形之外 —— 连通性可能是好的')
    A('r["lonely_tags"]       # [编号]  网络标签落了单(只有一个同号标签)')
    A('r["malformed_lines"]   # 坐标不是数字的 <line>, 会被解析器静默丢弃')
    A('r["nets"]              # {网id: [成员名]}    成员名如 "Q1.c" / "VCC"')
    A("```")
    A("")
    A("```bash")
    A("python .agents/skills/stm32-wiring-diagram/scripts/check_net.py \"工程目录/*.svg\"")
    A("python .agents/skills/stm32-wiring-diagram/scripts/check_net.py --show-nets \"工程目录/*.svg\"")
    A("```")
    A("")
    A("查**八类**：短路 / 旁路 / 穿体 / 悬空 / **接错**（自绘器件的 `expect` 没兑现）"
      "/ **畸形线段**（坐标不是数字，会被静默丢弃）"
      "/ **飘端子**（自绘端子离图形太远，导线接上了但看着像没接线）"
      "/ **孤标签**（网络标签 `marker()` 落了单 —— 同号才相连，只有一个等于没连）。")
    A("")
    A("> ⚠️ 这个检查器只证明**连对了**，不证明**参数选得对**。")
    A("> 静态工作点、增益、元件取值仍需自己核对。")
    A("")
    A("---")
    A("")

    # ---------- 5. 电气陷阱 ----------
    A("## 5. 电气陷阱（`verify()` 全查不出，肉眼也看不出）")
    A("")
    A("1. **竖直元件本体没有内置引线**，占 `cy±w/2`（电阻 w=42 → `cy±21`）、"
      "`cy±19`（电容）。引线只能从本体上下边缘起笔，**跨越本体 = 把它短路**。")
    A("2. **`npn` 的 `c` 与 `e` 同 x**（都在 `cx+s`）。两路都竖直走线会叠成"
      "一条 VCC→GND 导体，三极管被整体短路。必须横向错开。")
    A("3. **两端各接各的端子**。同一条支路两根线都从同一端子起笔，其中一根"
      "必然横穿元件本体。")
    A("4. **端点必须精确落在端子上**，差 1px 就是断路。用 `terminals()`，别写 `y+34`。")
    A("5. **交叉 ≠ 连接**。视觉交叉处没有 `junction()` 就不算相连；"
      "该连的地方一定要打 junction。")
    A("6. **`data-deco` 是装饰标记**（网格线/功能块外框/分隔线），两个检查器都跳过。"
      "自己写分析脚本时也必须过滤，否则网格线会被当成导线。")
    A("7. **接错节点**：端子接上了导线，但接的是**错的那个节点**。短路/旁路/"
      "穿体/悬空全都不报 —— 只有自绘器件的 `declare(expect=...)` 能发现。")
    A("8. **自绘符号的端子要落在自己画的图形上。** `declare(terminals=...)` 是"
      "**你手填的绝对坐标**，与符号内部的绘制代码之间没有任何一致性约束"
      "（内置符号有 `measure_symbols.py` 校准，自绘符号没有）。端子若悬在图形"
      "外，导线照样接得上、连通性完美，但图上看着像该元件没接线 —— "
      "只有 `[飘端子]` 这一类能抓。改符号的绘制代码后，务必同步 `terminals`。")
    A("")
    A("### 两个检查器的判定口径（写诊断时按这个理解）")
    A("")
    A("同一张图，两个检查器用的**不是同一套几何**，所以结论可能看着不一致：")
    A("")
    A("| | 用哪套几何 | 含义 |")
    A("|---|---|---|")
    A("| `verify()` 排版 | `_needs()` | 含标签的**外轮廓**，宁大勿小 |")
    A("| `analyze()` 电气 | `body_box()` | **只算本体**，必须精确 |")
    A("")
    A("另外三条口径：")
    A("")
    A("- **元件分组内部的线段不算导线**。`npn` 的斜引线、`push_button` 的横杆都在")
    A("  `<g data-sym>` 里，会被整组剔除 —— 否则它们会被当成真实导线。")
    A("- **连通判定**：端点相接才算连接；中途交叉不算，除非交点有 `junction()`。")
    A("- **容差**：`_on_segment` 默认 `tol=0.8px`。所以差 1px 就算断路，")
    A("  而「差不多接上了」在报告里会显示为具体的差距值。")
    A("")
    A("### 门禁**查不出**的东西（必须人工核对）")
    A("")
    A("- **极性/方向**：LED 阳极、电解电容正负、续流管方向、稳压管反接 —— "
      "两根线都接在正确端子上，连通性完美，任何检查都不报。")
    A("  用 `check_net.py --show-nets` 打出网表，逐个看方向性器件两端落在哪个网。")
    A("- **没 `declare()` 的自绘器件**：对检查器完全不可见。")
    A("- **自绘符号的端子声明与实际绘制是否一致**：`[飘端子]` 只抓「端子落在"
      "图形外」，抓不到「端子落在图形内、但落在错的那一段上」。")
    A("- **参数取值**：静态工作点、增益、元件数值。")
    A("")
    A("---")
    A("")

    # ---------- 6. 配置与自检脚本 ----------
    A("## 6. 配置读取与其他脚本")
    A("")
    A("```python")
    A('cfg = read_config("myproj")              # 工程目录')
    A('cfg["pins"]       # {"LED_R": ("PA0", "GPIOA"), ...}  引脚名与 mcu_block 一致')
    A('cfg["hse"]        # 8000000')
    A('cfg["pin_source"] # "main.h" 或 "ioc"')
    A("```")
    A("")
    A("`read_config(工程目录)` 从 `Core/Inc/main.h` → `.ioc` → `stm32f1xx_hal_conf.h` "
      "读引脚与时钟。**引脚一律从这里读，不要手抄**（手抄会过期，写错会烧片子）。")
    A("")
    A("### 引脚名要跟工程对照一次：`check_pins()`")
    A("")
    A("`mcu_block(pins_right=[(\"PA0\", 60)])` 里的引脚名是**手写字符串**，"
      "与 `read_config()` 读到的真实配置之间没有任何校验。工程改过、或手抄看错"
      "一行，图上就是错的, 而图看着完全正常（两道门也查不出 —— 引脚名只是个字符串）:")
    A("")
    A("```python")
    A('cfg = read_config("myproj")')
    A("check_pins('myproj', pins)          # pins = mcu_block 的引脚表")
    A("```")
    A("")
    A("报三类：工程里没有的引脚（画了源码中不存在的引脚）／漏画了的引脚"
      "／读不到配置。返回问题列表，空列表 = 全对。")
    A("")
    A("### 跨块连线：同号 `marker()` 就是同网")
    A("")
    A("```python")
    A("d.add(marker(x1, y1, 1))     # ①")
    A("d.add(marker(x2, y2, 1))     # ① —— 与上面电气相连(analyze 会并成一张网)")
    A("```")
    A("")
    A("**必须是成对的。** 只有一个同号标签时电气门报 `[孤标签]` —— "
      "它标了个什么也没连的东西（编号写错？或另一端忘了画？）。")
    A("")
    A("| 脚本 | 用途 |")
    A("|---|---|")
    A("| `check_svg.py` | 排版门 |")
    A("| `check_net.py` | 电气门 |")
    A("| `measure_symbols.py --check` | 符号尺寸标定（改了符号几何后跑） |")
    A("| `selftest.py` | 两个检查器的回归测试（含本页与代码是否一致） |")
    A("| `gen_quickref.py` | 生成本页 |")
    A("")
    A("---")
    A("")
    A("## 7. 完整示例")
    A("")
    A("**本页第 1 节的最小示例**是最可靠的起点 —— 它用到的每个 API 都在上面")
    A("各节里，照抄改参数即可。")
    A("")
    A("再复杂的电路，按形状拆成几段就行：串联段用 `chain()`、分支点用")
    A("`bus_net()`、段之间用 `link()`。自绘器件先 `register_symbol()` 再")
    A("`declare()`。")
    A("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="生成/校验接口速查页")
    ap.add_argument("--check", action="store_true",
                    help="只校验磁盘文件与代码是否一致, 不一致退出码 1")
    args = ap.parse_args()

    root = find_wirelib()
    if not root:
        print("错误: 找不到 wirelib.py", file=sys.stderr)
        return 2
    sys.path.insert(0, root)
    import wirelib as w

    text = build(w)
    out = os.path.abspath(OUT)

    if args.check:
        if not os.path.exists(out):
            print(f"[缺] {out} 不存在 —— 跑一遍 gen_quickref.py")
            return 1
        old = open(out, encoding="utf-8").read()
        if old != text:
            print(f"[过期] {out} 与 wirelib.py 不一致 —— 重跑 gen_quickref.py")
            return 1
        print("quickref.md 与 wirelib.py 一致。")
        return 0

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已生成: {out}  ({len(text)} 字节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
