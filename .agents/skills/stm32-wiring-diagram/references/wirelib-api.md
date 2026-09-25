> **画图时优先读 `quickref.md`**（自动生成的一页速查，含符号签名/端子/包围盒/
> 两个检查器/电气陷阱）。**本文件只收录 quickref 里没有的内容** —— 基础图元、
> 配色常量、`Box`、`marker`。

# wirelib 补充 API

`wirelib.py` 位于 `D:\SCM\`，所有工程共用。脚本里这样导入：

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wirelib import *
```

坐标系统：SVG 惯例，**左上角为原点，y 向下**，单位像素。

---

## 基础图元

自绘器件时用这几个拼：

```python
text(x, y, s, size=13, anchor="start", color=FG, weight="normal")
line(x1, y1, x2, y2, color=WIRE, w=2, dash=None)
rect(x, y, w, h, fill="none", stroke=FG, sw=1.5, rx=0)
circle(cx, cy, r, fill="none", stroke=FG, sw=1.5)
polygon(points, fill, stroke=None, sw=1)      # points = [(x,y), ...]
junction(cx, cy, r=3.5, color=WIRE)           # 导线连接点(实心圆)
```

`anchor` 取 `"start"`（左对齐）/ `"middle"`（居中）/ `"end"`（右对齐）。
注意 `y` 是**基线**位置，不是文字顶部。

配色常量：`FG`(黑) `DIM`(灰) `WIRE`(导线) `LEDC`(红) `RESC`(蓝) `GNDC`(深灰)
`VC`(电源红) `NPB`(三极管紫)。

> ⚠️ **别把颜色常量当成坐标用。** 实测踩过：一个局部变量遮蔽了 `WIRE`，
> 于是画出 `<line x1="#37474f" ...>` —— 坐标不是数字，被解析器**静默丢弃**，
> 接着报出一片假的「悬空/旁路」，真病因反而被埋掉。
> `check_net.py` 有 `[畸形]` 一类专门报这个，报出来时先修它。

---

## 网络标签 `marker`

跨功能块的信号不要拉长实线穿过去，用同号标签表示相连：

```python
d.add(marker(x1, y1, 1))     # ①
d.add(marker(x2, y2, 1))     # ① 与上面电气相连
```

`marker` 故意画在导线端点，所以带 `data-node` 标记，自检器会跳过它们
（不会误报「文字压线」）。

---

## 包围盒累加器 `Box`

把一组图元当成一个整体登记。用于自绘器件，或想让告警定位到具体部件时：

```python
b = Box("驱动级")
b.add_item(q_svg,  683, 435, 777, 469, kind="元件", name="Q1")
b.add_item(led_svg, 800, 380, 826, 440, kind="元件", name="LED_R")
d.add(bounds=b)          # 一次把 b.parts 加进去并把 b.items 登记给自检器
print(b.bounds)          # 整组的 (x0,y0,x1,y1)
```

内置符号**不需要**手写 `Box` —— 它们返回的 SVG 外层带 `data-sym` 标记，
`Doc.add()` 会自动按 `_needs()` 的标定尺寸登记包围盒。

若给 `d.add()` 传了 `kind`/`name` 却没给 `bounds`、而图元又不是内置符号
（没有 `data-sym`），`add()` 会**直接报错**而不是静默不登记 —— 提示你补
`bounds=(x0,y0,x1,y1)`。
