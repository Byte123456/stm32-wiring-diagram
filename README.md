# stm32-wiring-diagram

用 Python 生成 STM32 接线图 / 原理图（SVG），**带两道自动检查门禁**。

给 AI coding agent 用的：agent 只需声明「什么连什么」，坐标由库算出来，
再由检查器验证「连得通不通、排得好不好看」。

```python
import sys; sys.path.insert(0, ".")      # 含 wirelib.py 的目录
from wirelib import *

d = Doc("LED 闪烁", "PC13 推挽输出")
mcu_svg, ends = mcu_block(60, 150, 190, 280, "STM32F103C8T6",
                          pins_right=[("PC13", 60)])
d.add(mcu_svg)

chain(d, ends["PC13"], [                 # 串联支路: 引脚→电阻→LED→GND
    ("R", resistor, dict(w=42, h=15), "1K"),
    ("L", led,      dict(s=13, direction=1), "LED"),
], to_ground=True)

d.save("led.svg")                        # 标注自动落位
```

---

## 为什么需要它

让大模型直接输出电路坐标，必然出现**差几像素的断线**。这类错误最麻烦的地方在于
它看不出来 —— 图上线条笔直、元件规整，渲染成图片给人看也看不出问题，但实际是断的。

实测这个库上线网表检查时，在**已经人工"验收通过"的图**里当场抓出 7 处真实缺陷：
集电极引线差 13px 悬空、每个耦合电容两端各差 8px、晶振两极差 34px 全断、
若干 LED 的引线横穿本体把 LED 短路。

所以本项目的两条设计原则是：

1. **能结构性避免的错误，不靠检查去发现。** 布局工具（`chain` / `bus_net` / `link`）
   从符号自己的端子表算坐标，人手不接触数字。
2. **检查器要能抓"看着没问题"的错误。** 把图还原成网表做连通性分析，而不是看外观。

---

## 两道门禁

缺一不算交付。

```bash
python .agents/skills/stm32-wiring-diagram/scripts/check_svg.py  "myproj/*.svg"   # 排版
python .agents/skills/stm32-wiring-diagram/scripts/check_net.py  "myproj/*.svg"   # 电气
```

| 排版门（7 类） | 电气门（8 类） |
|---|---|
| 文字互相重叠 | **短路** VCC 与 GND 同网 |
| 文字压在长导线上 | **旁路** 元件两端同网（形同不存在） |
| 平行水平线过近 | **穿体** 导线纵穿元件本体 |
| 平行竖线过近 | **悬空** 端子没接到导线（差几像素） |
| 器件超出画布 | **接错** 自绘器件声明该接哪却没兑现 |
| 器件互相重叠 | **畸形线段** 坐标不是数字，被静默丢弃 |
| 文字超出画布 | **飘端子** 自绘端子离画出的图形太远 |
| | **孤标签** 网络标签落了单 |

**报告直接带改法**，不用自己想"该挪多少"：

```
[器件重叠] 40x30px  R1 <-> L1  → 垂直分开 ≥38px（把 R1 上移到 y≤247, 或把 L1 下移到 y≥353）
[悬空] Q1.c 差 13.0px          → 把该引线端点移到 y=498.0
[飘端子] K1线圈.n 离开图形 17.0px → 该端子在 (739..781) 的图形之外, 改 declare(terminals=...)
```

### ⚠️ 门禁**查不出**什么

这一点值得单独强调，因为它决定了怎么用这套工具：

- **极性 / 方向**。LED 阳极接到地、电解电容正负反、续流管方向反 —— 两根线都接在
  正确端子上，连通性完美，全部检查返回 0。**必须人工核对**（文档给了方向性器件对照表）。
- **连着的东西对不对**。图可能**忠实实现了错误的意图**。实测过一次：一条横贯全图的
  +V 母线把 3.3V 域和 5V 域短在一起，两道门都报 0。
- **参数取值**。静态工作点、增益、元件数值。

所以画完**必须打印网表逐条核对**：`check_net.py --show-nets`。

---

## 布局工具

按电路形状选工具 —— 选错了就得手算坐标，而手算坐标是几乎所有缺陷的成因。

| 电路形状 | 用什么 |
|---|---|
| 串联支路（一进一出） | `chain()` |
| 分支节点（一节点接 3~4 路） | `bus_net()` |
| 两段支路之间的连线 | `link()` |
| 纯连接关系已知，不想碰坐标 | `net2svg()`（仅单主干） |
| 自绘器件（继电器/光敏管/MOS） | `register_symbol()` + `declare()` |

```python
# 分支节点: 一根竖直母线, 各支路按方向挂出去
bus_net(d, cx=400, y0=200, y1=700, label="A", branches=[
    ("D1", "up",   0.0,  "led",      dict(s=13, direction=1), "光敏"),
    ("R1", "down", 0.35, "resistor", dict(w=42, h=15), "10K"),
])

# 母线到 MCU 引脚
link(d, bus["ends"]["R1"], ends["PA0"])
```

**接线端点一律来自 `terminals()` 或符号返回值**，不要手填偏移。

### 自绘器件

`analyze()` 只认识库里注册过的符号。自己拼的器件（继电器、MOS、传感器模块）
对它**完全不可见** —— 不是"查了没问题"，是"压根没看"：

```python
d.add(declare(coil_svg, "K1线圈",
              terminals={"t": (640, 268), "b": (640, 312)},   # 绝对坐标
              body=(617, 268, 663, 312),
              expect={"b": "npn.c"}))                         # 该端应在哪个网
```

`expect` 是**唯一能抓住"接到错的那个节点"**的手段。

---

## 自检与文档防漂移

```bash
python .agents/skills/stm32-wiring-diagram/scripts/selftest.py            # 51 个用例
python .agents/skills/stm32-wiring-diagram/scripts/measure_symbols.py --check
```

检查器都是"减法"工具 —— 靠一堆阈值把正常情况排除掉，只留真问题。**调阈值时最容易
的失误是顺手把真问题也排除掉**，而那样它们会一路返回 0，看起来"图都干净了"。
所以每个检查都配一个"必须报"的用例和一个"不能报"的用例。

`references/quickref.md` 是从 `wirelib.py` **反射生成**的（符号签名、端子坐标、
包围盒尺寸全部当场实测），`selftest.py` 断言磁盘文件与代码逐字节一致 ——
所以文档不可能和实现漂移。

---

## 目录

```
wirelib.py                                    器件符号库 + 画布 + 两个检查器（~2500 行）
.agents/skills/stm32-wiring-diagram/
├── SKILL.md                                  工作流、电气陷阱、检查清单
├── references/
│   ├── quickref.md                           接口速查（自动生成，画图先读这页）
│   └── wirelib-api.md                        补充 API（基础图元、Box、marker）
└── scripts/
    ├── check_svg.py / check_net.py           两道门禁
    ├── selftest.py                           回归测试（51 用例）
    ├── measure_symbols.py                    符号尺寸标定
    ├── gen_quickref.py                       生成 quickref
    └── _paths.py                             定位 wirelib.py（可移植）
docs/                                          CHANGELOG + 一次真实会话的复盘
```

## 环境

- Python 3.8+（只用到标准库）
- 可选：`svglib` + `reportlab`（`check_svg.py --png` 渲染预览用；缺了只是跳过渲染）
- 无第三方运行时依赖。生成的 SVG 可直接用浏览器打开（中文标注正常显示）。

## 说明

- 图中所有坐标由符号的端子表算出，**尺寸是量出来的不是估的**（`measure_symbols.py`）。
- 库不依赖任何第三方运行时，生成的 SVG 可直接用浏览器打开。
- `read_config()` 从 STM32 工程的 `Core/Inc/main.h` / `.ioc` 读引脚，
  **不要手抄引脚表** —— 手抄会过期，写错会烧片子。用法见 quickref。
