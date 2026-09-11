# -*- coding: utf-8 -*-
"""main.py — 应用入口"""

import math
import sys

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QColor, QPen,
)
from PySide6.QtWidgets import QApplication

from config import GLOBAL_QSS
from main_window import MainWindow


# ═══════════════════════════════════════════════════════════════════
# 应用图标（代码绘制，无外部文件，无 PIL 依赖）
# ═══════════════════════════════════════════════════════════════════

# 设计基准：所有坐标基于 64×64 画布，其他尺寸按比例缩放
_ICON_DESIGN_SIZE = 64.0
_LINE_COLOR       = "#9498a0"    # 灰色轮廓
_TEAL_COLOR       = "#248888"    # 青蓝色
_BG_COLOR         = "#ffffff"    # 白色背景
_LINE_WIDTH_AT_64 = 2.0


def _render_icon(size: int) -> QPixmap:
    """绘制压力表 + 管道的图标"""
    s = float(size)
    k = s / _ICON_DESIGN_SIZE                     # 缩放因子

    line_color = QColor(_LINE_COLOR)
    teal_color = QColor(_TEAL_COLOR)
    lw       = max(1, int(round(_LINE_WIDTH_AT_64 * k)))   # 普通线宽
    lw_teal  = max(1, int(round(3.0 * k)))                 # 青色弧线宽

    pm = QPixmap(size, size)
    pm.fill(QColor(_BG_COLOR))

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = s / 2.0, s / 2.0

    line_pen = QPen(line_color, lw)
    line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    # ── 1. 外层圆角方形外壳 ──
    margin = 8.0 * k
    p.setPen(line_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(margin, margin, s - 2 * margin, s - 2 * margin - 6 * k),
        6 * k, 6 * k,
    )

    # ── 2. 外壳顶部小提手 ──
    p.drawRoundedRect(QRectF(22 * k, 10 * k, 20 * k, 6 * k), 3 * k, 3 * k)

    # ── 3. 压力表表盘 ──
    gauge_r = 18.0 * k
    arc_cx, arc_cy = cx, cy - 4.0 * k
    arc_rect = QRectF(arc_cx - gauge_r, arc_cy - gauge_r,
                      gauge_r * 2, gauge_r * 2)

    # 青色弧（PIL 30° → 160°，顺时针 130°）
    # Qt 换算：startAngle=-30×16，spanAngle=-130×16（负号=顺时针）
    teal_pen = QPen(teal_color, lw_teal)
    teal_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(teal_pen)
    p.drawArc(arc_rect, -30 * 16, -130 * 16)

    # 灰色弧（PIL 160° → 390°，顺时针 230°）
    gray_pen = QPen(line_color, lw)
    gray_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(gray_pen)
    p.drawArc(arc_rect, -160 * 16, -230 * 16)

    # ── 4. 表盘刻度短线（数学角度：逆时针从 3 点钟） ──
    tick_positions = [45, 85, 125, 155]
    p.setPen(line_pen)
    for ang in tick_positions:
        rad = math.radians(ang)
        x1 = arc_cx + (gauge_r - 3 * k) * math.cos(rad)
        y1 = arc_cy - (gauge_r - 3 * k) * math.sin(rad)
        x2 = arc_cx + (gauge_r - 7 * k) * math.cos(rad)
        y2 = arc_cy - (gauge_r - 7 * k) * math.sin(rad)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    # ── 5. 指针（数学角度 110°） ──
    needle_angle = math.radians(110.0)
    needle_len = gauge_r - 4.0 * k
    nx = arc_cx + needle_len * math.cos(needle_angle)
    ny = arc_cy - needle_len * math.sin(needle_angle)
    p.drawLine(QPointF(arc_cx, arc_cy), QPointF(nx, ny))

    # ── 6. 中心圆点 ──
    p.drawEllipse(QPointF(arc_cx, arc_cy), 3 * k, 3 * k)

    # ── 7. 底部接头方块（灰框 + 青蓝填充） ──
    p.setPen(line_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(
        QRectF(cx - 7 * k, cy + 12 * k, 14 * k, 10 * k),
        2 * k, 2 * k,
    )
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(teal_color)
    p.drawRect(QRectF(cx - 4 * k, cy + 14 * k, 8 * k, 6 * k))

    # ── 8. 下方细管道 ──
    p.setPen(line_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(cx - 3 * k, cy + 22 * k, 6 * k, 8 * k))

    # ── 9. 底部小圆头 ──
    p.drawEllipse(QRectF(cx - 4 * k, cy + 28 * k, 8 * k, 6 * k))

    p.end()
    return pm


def _make_app_icon() -> QIcon:
    """多尺寸合成：标题栏 / 任务栏 / Alt+Tab 都清晰"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_icon(size))
    return icon


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)

    # 系统未提供有效字号时补一个，避免 Qt 打印
    # "QFont::setPointSize: Point size <= 0 (-1)" 警告
    f = app.font()
    if f.pixelSize() <= 0 and f.pointSize() <= 0:
        f.setPixelSize(14)
        app.setFont(f)

    # ★ 应用图标：一次性设置，作用于所有窗口
    app.setWindowIcon(_make_app_icon())

    app.setStyleSheet(GLOBAL_QSS)
    app.setApplicationName("气密性测试")

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()