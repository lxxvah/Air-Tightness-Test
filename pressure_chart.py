# -*- coding: utf-8 -*-
"""
pressure_chart.py — 实时压力曲线（独立模块）

两种启动方式：
  · start(target)       — 全新开始：清空数据、清空轮次标记、重置 t0
  · start_round(target) — 批量中间轮：保留数据、保留 t0、记一个轮次分隔点

target 红线：
  · set_target_visible(True/False) 控制是否绘制

轮次分隔线：
  · 每次 start_round() 自动打一个标记
"""

import time
from collections import deque

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QFont, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QSizePolicy

from config import COLORS as C, TEST_DEFAULTS


class PressureChart(QWidget):
    """实时压力曲线（QPainter 手绘）"""

    MAX_POINTS = 20000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._data: deque = deque(maxlen=self.MAX_POINTS)
        self._target = TEST_DEFAULTS["pressure"]
        self._t0 = None
        self._active = False

        self._show_target = True
        self._round_marks: list = []

    # ── 全新开始 ──
    def start(self, target: int) -> None:
        self._data.clear()
        self._round_marks.clear()
        self._target = target
        self._t0 = time.time()
        self._active = True
        self._show_target = True          # ← 新增：全新开始一定显示 TARGET 线
        self.update()

    # ── 批量中间轮 ──
    def start_round(self, target: int) -> None:
        if self._t0 is None:
            self._t0 = time.time()
            self._data.clear()
            self._round_marks.clear()
        else:
            self._round_marks.append(time.time() - self._t0)
        self._target = target
        self._active = True
        self.update()

    def has_data(self) -> bool:
        return len(self._data) > 0

    def set_target_visible(self, visible: bool) -> None:
        if self._show_target != visible:
            self._show_target = visible
            self.update()

    def stop(self) -> None:
        self._active = False
        self.update()

    def push(self, pressure: float) -> None:
        if self._t0 is None:
            self._t0 = time.time()
            self._active = True
        self._data.append((time.time() - self._t0, pressure))
        self.update()

    def clear(self) -> None:
        self._data.clear()
        self._round_marks.clear()
        self._t0 = None
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C["canvas"]))

        L, R, T, B = 54, 18, 18, 30
        plot = self.rect().adjusted(L, T, -R, -B)
        if plot.width() < 20 or plot.height() < 20:
            return

        y_max = max(self._target * 1.25, 320)
        y_min = 0

        grid_pen = QPen(QColor("#f0f0f0"))
        grid_pen.setWidth(1)
        tick_font = QFont()
        tick_font.setPixelSize(10)
        p.setFont(tick_font)

        n = 4
        for i in range(n + 1):
            y = plot.bottom() - i * plot.height() / n
            p.setPen(grid_pen)
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            val = y_min + i * (y_max - y_min) / n
            p.setPen(QColor(C["mute"]))
            p.drawText(0, int(y) - 8, L - 10, 16,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:.0f}")

        # 时间轴上限
        if self._data:
            t_max = max(30.0, self._data[-1][0] * 1.08)
        else:
            t_max = 30.0

        # 轮次分隔线
        if self._round_marks:
            mark_pen = QPen(QColor("#e8e8e8"))
            mark_pen.setWidth(1)
            p.setPen(mark_pen)
            for t_mark in self._round_marks:
                x = plot.left() + (t_mark / t_max) * plot.width()
                if plot.left() <= x <= plot.right():
                    p.drawLine(int(x), int(plot.top()),
                               int(x), int(plot.bottom()))

        # target 红线
        if self._show_target and self._target > 0:
            ty = plot.bottom() - (self._target - y_min) / (y_max - y_min) * plot.height()
            dash = QPen(QColor(C["red"]))
            dash.setStyle(Qt.PenStyle.DashLine)
            dash.setWidth(1)
            p.setPen(dash)
            p.drawLine(int(plot.left()), int(ty), int(plot.right()), int(ty))
            p.setPen(QColor(C["red"]))
            p.drawText(int(plot.left()) + 6, int(ty) - 16, 160, 16,
                       Qt.AlignmentFlag.AlignLeft,
                       f"TARGET  {self._target} mmHg")

        # 压力曲线
        if len(self._data) >= 2:
            pen = QPen(QColor(C["primary"]))
            pen.setWidth(2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)

            pts = []
            for t, val in self._data:
                x = plot.left() + (t / t_max) * plot.width()
                y = plot.bottom() - ((val - y_min) / (y_max - y_min)) * plot.height()
                y = max(plot.top() + 1, min(plot.bottom() - 1, y))
                pts.append(QPointF(x, y))

            for i in range(1, len(pts)):
                p.drawLine(pts[i - 1], pts[i])

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C["primary"]))
            p.drawEllipse(pts[-1], 3.0, 3.0)

        # 坐标轴
        axis = QPen(QColor(C["hairline"]))
        axis.setWidth(1)
        p.setPen(axis)
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        p.drawLine(plot.topLeft(), plot.bottomLeft())

        p.setPen(QColor(C["mute"]))
        p.drawText(int(plot.left()), int(plot.bottom()) + 6, 60, 18,
                   Qt.AlignmentFlag.AlignLeft, "0 s")
        if self._data:
            p.drawText(int(plot.right()) - 80, int(plot.bottom()) + 6, 80, 18,
                       Qt.AlignmentFlag.AlignRight, f"{t_max:.0f} s")
        p.drawText(int(plot.right()) - 100, int(plot.top()) + 2, 100, 16,
                   Qt.AlignmentFlag.AlignRight, "mmHg")