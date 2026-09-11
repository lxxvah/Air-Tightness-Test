# -*- coding: utf-8 -*-
"""
batch_test_dialog.py — 批量测试对话框（多压力档）

设计：
  · 顶栏：BATCH TEST + 批量测试 + 状态圆点 + 状态文字 + 轮次 + 合格/不合格
  · 提示行：压力档说明
  · 压力档表格（3~8 行自适应，表头与内容都居中）
  · 合并行（等分铺满）：间隔 / 失败时中止 —— 总次数 · 预计 · 累计 —— 添加压力档
  · 进度文字
  · 结果表格（表头与内容居中）
  · 底部按钮：清空曲线 / 打开测试结果 / 取消 / 开始批量

信号（发给 MainWindow）：
  · batch_started(plan: list, options: dict)
  · batch_stop_requested()
  · clear_chart_requested()                    请求主窗口清空压力曲线

回调（由 MainWindow 调用）：
  · notify_test_started(index, total, params)
  · notify_test_result(index, result)
  · notify_batch_finished(reason)
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFrame,
)

from config import (
    COLORS as C, PROTOCOL, TEST_DEFAULTS, TEST_RANGES, BATCH_DEFAULTS,
    TEST_RUNTIME,
)

import report_manager


class BatchTestDialog(QDialog):
    """批量测试：多组 (压力, 时长, 阈值, 次数) 循环执行"""

    batch_started         = Signal(list, dict)
    batch_stop_requested  = Signal()
    clear_chart_requested = Signal()

    COL_PRESSURE  = 0
    COL_DURATION  = 1
    COL_THRESHOLD = 2
    COL_COUNT     = 3
    COL_ACTION    = 4

    STEP_ROW_HEIGHT = 40
    STEP_ROWS_MIN   = 3
    STEP_ROWS_MAX   = 8

    RESET_TIME_SEC  = 0.4
    OBSERVATION_SEC = TEST_RUNTIME["observation_sec"]

    def __init__(self, base_params: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量测试")
        self.setModal(False)
        self.resize(920, 720)
        self.setStyleSheet(f"QDialog {{ background: {C['canvas']}; }}")

        self._base = dict(base_params)
        self._running = False
        self._total_plan = 0

        self._elapsed_t0 = 0.0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()

        self._add_step_row(
            self._base.get("pressure",  TEST_DEFAULTS["pressure"]),
            self._base.get("duration",  TEST_DEFAULTS["duration"]),
            self._base.get("threshold", TEST_DEFAULTS["threshold"]),
            BATCH_DEFAULTS["count"],
        )
        self._update_total_hint()

    # ══════════════════════════════════════════════════════════════
    # UI
    # ══════════════════════════════════════════════════════════════
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── 顶栏 ──
        head = QHBoxLayout()
        head.setSpacing(16)

        eb = QLabel("BATCH TEST")
        eb.setStyleSheet(f"color:{C['mute']}; font-size:12px; font-weight:500;")
        f = QFont(); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        eb.setFont(f)
        head.addWidget(eb)

        title = QLabel("批量测试")
        title.setStyleSheet(f"color:{C['ink']}; font-size:20px; font-weight:500;")
        head.addWidget(title)

        head.addSpacing(24)

        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.dot.setStyleSheet(f"background:{C['mute_soft']}; border-radius:5px;")
        head.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self.lbl_batch_status = QLabel("空闲")
        self.lbl_batch_status.setStyleSheet(
            f"color:{C['ink']}; font-size:13px; font-weight:500;")
        head.addWidget(self.lbl_batch_status)

        head.addSpacing(20)

        self.lbl_round = QLabel("— / —")
        self.lbl_round.setStyleSheet(
            f"color:{C['body_mid']}; font-size:13px; font-weight:500;")
        head.addWidget(self.lbl_round)

        head.addSpacing(20)

        self.lbl_pass = QLabel("✅ 0")
        self.lbl_pass.setStyleSheet(
            f"color:{C['green']}; font-size:13px; font-weight:600;")
        head.addWidget(self.lbl_pass)

        self.lbl_fail = QLabel("❌ 0")
        self.lbl_fail.setStyleSheet(
            f"color:{C['red']}; font-size:13px; font-weight:600;")
        head.addWidget(self.lbl_fail)

        head.addStretch()
        lay.addLayout(head)

        # ── 提示行 ──
        hint = QLabel("压力档 · 每个档位按指定次数循环执行")
        hint.setStyleSheet(f"color:{C['body_mid']}; font-size:12px;")
        lay.addWidget(hint)

        # ── 压力档表格 ──
        self.step_table = QTableWidget(0, 5)
        self.step_table.setHorizontalHeaderLabels(
            ["目标压力", "稳压时间", "合格阈值", "次数", ""])
        self.step_table.verticalHeader().setVisible(False)
        self.step_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.step_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.step_table.setShowGrid(False)
        self.step_table.setMinimumHeight(170)
        self.step_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['canvas']};
                border:1px solid {C['hairline']};
                border-radius:8px;
                font-size:13px;
            }}
            QHeaderView::section {{
                background:{C['canvas']};
                color:{C['mute']};
                border:none;
                border-bottom:1px solid {C['hairline']};
                padding:8px 12px;
                font-weight:500;
                font-size:12px;
            }}
        """)
        hdr = self.step_table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setSectionResizeMode(self.COL_PRESSURE,  QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_DURATION,  QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_THRESHOLD, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_COUNT,     QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_ACTION,    QHeaderView.ResizeMode.Fixed)
        self.step_table.setColumnWidth(self.COL_ACTION, 90)
        lay.addWidget(self.step_table)

        # ── 合并行 ──
        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)
        opt_row.setContentsMargins(0, 0, 0, 0)

        opt_row.addWidget(self._mk_label("间隔 (s)"))

        self.inp_interval = QDoubleSpinBox()
        self.inp_interval.setRange(0.0, 300.0)
        self.inp_interval.setDecimals(1)
        self.inp_interval.setValue(BATCH_DEFAULTS["interval"])
        self.inp_interval.setFixedHeight(34)
        _w = self.inp_interval.fontMetrics().horizontalAdvance("300.0") + 36
        self.inp_interval.setFixedWidth(_w)
        self.inp_interval.setStyleSheet(self._inline_spin_qss())
        self.inp_interval.valueChanged.connect(self._update_total_hint)
        opt_row.addWidget(self.inp_interval, 0, Qt.AlignmentFlag.AlignVCenter)

        self.chk_stop = QCheckBox("失败时中止")
        self.chk_stop.setChecked(BATCH_DEFAULTS["stop_on_fail"])
        self.chk_stop.setStyleSheet(f"color:{C['body']}; font-size:13px;")
        opt_row.addWidget(self.chk_stop)

        opt_row.addStretch(1)

        self.lbl_total = QLabel("总次数：0")
        self.lbl_total.setStyleSheet(
            f"color:{C['ink']}; font-size:13px; font-weight:600;")
        opt_row.addWidget(self.lbl_total)

        sep1 = QLabel("·")
        sep1.setStyleSheet(f"color:{C['mute_soft']}; font-size:13px;")
        opt_row.addWidget(sep1)

        self.lbl_estimate = QLabel("预计：—")
        self.lbl_estimate.setStyleSheet(
            f"color:{C['ink']}; font-size:13px; font-weight:600;")
        opt_row.addWidget(self.lbl_estimate)

        sep2 = QLabel("·")
        sep2.setStyleSheet(f"color:{C['mute_soft']}; font-size:13px;")
        opt_row.addWidget(sep2)

        self.lbl_elapsed = QLabel("累计：0 秒")
        self.lbl_elapsed.setStyleSheet(
            f"color:{C['body_mid']}; font-size:13px; font-weight:600;")
        opt_row.addWidget(self.lbl_elapsed)

        opt_row.addStretch(1)

        self.btn_add_step = QPushButton("+  添加压力档")
        self.btn_add_step.setObjectName("ButtonSecondary")
        self.btn_add_step.setFixedHeight(34)
        self.btn_add_step.setStyleSheet(
            f"QPushButton {{"
            f"  background:{C['canvas']}; color:{C['ink']};"
            f"  border:1px solid {C['hairline']}; border-radius:4px;"
            f"  font-size:13px; padding: 4px 14px; }}"
            f"QPushButton:hover {{ border-color:{C['ink']}; }}")
        self.btn_add_step.clicked.connect(self._on_add_step)
        opt_row.addWidget(self.btn_add_step)

        lay.addLayout(opt_row)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C['hairline']};")
        lay.addWidget(sep)

        # ── 进度文字 ──
        self.lbl_progress = QLabel("等待开始")
        self.lbl_progress.setStyleSheet(f"color:{C['body_mid']}; font-size:13px;")
        lay.addWidget(self.lbl_progress)

        # ── 结果表格 ──
        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(
            ["#", "时间", "目标压力", "稳定压", "漏气率", "判定"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.result_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_table.setShowGrid(False)
        self.result_table.setStyleSheet(f"""
            QTableWidget {{
                background:{C['canvas']};
                border:1px solid {C['hairline']};
                border-radius:8px;
                font-size:13px;
            }}
            QHeaderView::section {{
                background:{C['canvas']};
                color:{C['mute']};
                border:none;
                border-bottom:1px solid {C['hairline']};
                padding:8px 12px;
                font-weight:500;
                font-size:12px;
            }}
        """)
        rh = self.result_table.horizontalHeader()
        rh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        rh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.result_table, 1)

        # ── 底部按钮：清空曲线 / 打开测试结果 / 取消 / 开始批量 ──
        btns = QHBoxLayout()
        btns.addStretch()

        self.btn_clear_chart = QPushButton("清空曲线")
        self.btn_clear_chart.setObjectName("ButtonSecondary")
        self.btn_clear_chart.clicked.connect(self._on_clear_chart)
        btns.addWidget(self.btn_clear_chart)

        self.btn_open_results = QPushButton("打开测试结果")
        self.btn_open_results.setObjectName("ButtonSecondary")
        self.btn_open_results.clicked.connect(report_manager.open_results_folder)
        btns.addWidget(self.btn_open_results)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("ButtonSecondary")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btns.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("开始批量")
        self.btn_start.setObjectName("ButtonPrimary")
        self.btn_start.clicked.connect(self._on_start)
        btns.addWidget(self.btn_start)

        lay.addLayout(btns)

    @staticmethod
    def _mk_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color:{C['body_mid']}; font-size:12px; font-weight:500;")
        return lbl

    @staticmethod
    def _inline_spin_qss() -> str:
        return (
            f"QDoubleSpinBox {{"
            f"  background:{C['canvas']};"
            f"  border:1px solid {C['hairline']};"
            f"  border-radius:4px;"
            f"  padding: 4px 8px;"
            f"  font-size: 13px; }}"
            f"QDoubleSpinBox:focus {{ border-color:{C['ink']}; }}"
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
            f"  width:0; height:0; border:none; }}")

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        if seconds <= 0:
            return "—"
        s = int(round(seconds))
        if s < 60:
            return f"{s} 秒"
        if s < 3600:
            m, sec = divmod(s, 60)
            return f"{m} 分 {sec} 秒" if sec else f"{m} 分"
        h, rem = divmod(s, 3600)
        m = rem // 60
        return f"{h} 小时 {m} 分" if m else f"{h} 小时"

    def _set_batch_status(self, state: str, text: str = None):
        color_map = {
            "idle":    C["mute_soft"],
            "running": C["blue_info"],
            "pass":    C["green"],
            "fail":    C["red"],
            "stopped": C["orange"],
        }
        text_map = {
            "idle":    "空闲",
            "running": "运行中",
            "pass":    "已完成",
            "fail":    "已完成",
            "stopped": "已停止",
        }
        color = color_map.get(state, C["mute_soft"])
        self.dot.setStyleSheet(f"background:{color}; border-radius:5px;")
        self.lbl_batch_status.setText(text or text_map.get(state, "空闲"))

    def _tick_elapsed(self):
        if self._elapsed_t0 <= 0:
            return
        from time import time as _now
        elapsed = _now() - self._elapsed_t0
        self.lbl_elapsed.setText(f"累计：{self._fmt_duration(elapsed)}")

    # ══════════════════════════════════════════════════════════════
    # 压力档增删
    # ══════════════════════════════════════════════════════════════
    def _add_step_row(self, pressure: int, duration: int,
                      threshold: float, count: int):
        row = self.step_table.rowCount()
        self.step_table.insertRow(row)
        self.step_table.setRowHeight(row, self.STEP_ROW_HEIGHT)

        sp_p = QSpinBox()
        sp_p.setRange(*TEST_RANGES["pressure"])
        sp_p.setValue(pressure)
        sp_p.setSuffix(" mmHg")
        sp_p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_p.setStyleSheet(self._cell_spin_qss())
        sp_p.valueChanged.connect(self._update_total_hint)
        self.step_table.setCellWidget(row, self.COL_PRESSURE, sp_p)

        sp_d = QSpinBox()
        sp_d.setRange(*TEST_RANGES["duration"])
        sp_d.setValue(duration)
        sp_d.setSuffix(" s")
        sp_d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_d.setStyleSheet(self._cell_spin_qss())
        sp_d.valueChanged.connect(self._update_total_hint)
        self.step_table.setCellWidget(row, self.COL_DURATION, sp_d)

        sp_t = QDoubleSpinBox()
        sp_t.setRange(*TEST_RANGES["threshold"])
        sp_t.setDecimals(2)
        sp_t.setSingleStep(0.1)
        sp_t.setValue(threshold)
        sp_t.setSuffix(" mmHg/min")
        sp_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_t.setStyleSheet(self._cell_spin_qss())
        self.step_table.setCellWidget(row, self.COL_THRESHOLD, sp_t)

        sp_c = QSpinBox()
        sp_c.setRange(1, 999)
        sp_c.setValue(count)
        sp_c.setSuffix(" 次")
        sp_c.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp_c.setStyleSheet(self._cell_spin_qss())
        sp_c.valueChanged.connect(self._update_total_hint)
        self.step_table.setCellWidget(row, self.COL_COUNT, sp_c)

        btn_del = QPushButton("删除")
        btn_del.setStyleSheet(
            f"QPushButton {{ background:{C['canvas']}; color:{C['ink']};"
            f" border:1px solid {C['hairline']}; border-radius:4px;"
            f" font-size:12px; padding: 4px 8px; }}"
            f"QPushButton:hover {{ border-color:{C['ink']}; }}")
        btn_del.clicked.connect(self._on_delete_row)
        self.step_table.setCellWidget(row, self.COL_ACTION, btn_del)

        self._adjust_step_height()

    @staticmethod
    def _cell_spin_qss() -> str:
        return (
            f"QSpinBox, QDoubleSpinBox {{"
            f"  background:{C['canvas']};"
            f"  border:1px solid {C['hairline']};"
            f"  border-radius:4px;"
            f"  padding: 4px 8px;"
            f"  font-size: 12px; }}"
            f"QSpinBox:focus, QDoubleSpinBox:focus {{"
            f"  border-color:{C['ink']}; }}"
            f"QSpinBox::up-button, QSpinBox::down-button,"
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
            f"  width:0; height:0; border:none; }}")

    def _adjust_step_height(self):
        rows = self.step_table.rowCount()
        rows = max(rows, self.STEP_ROWS_MIN)
        rows = min(rows, self.STEP_ROWS_MAX)
        header_h = self.step_table.horizontalHeader().height()
        h = header_h + rows * self.STEP_ROW_HEIGHT + 8
        self.step_table.setFixedHeight(h)

    def _on_add_step(self):
        last_p = TEST_DEFAULTS["pressure"]
        if self.step_table.rowCount() > 0:
            w = self.step_table.cellWidget(
                self.step_table.rowCount() - 1, self.COL_PRESSURE)
            if w:
                last_p = w.value()
        self._add_step_row(
            last_p,
            self._base.get("duration",  TEST_DEFAULTS["duration"]),
            self._base.get("threshold", TEST_DEFAULTS["threshold"]),
            1,
        )
        self._update_total_hint()

    def _on_delete_row(self):
        btn = self.sender()
        for row in range(self.step_table.rowCount()):
            if self.step_table.cellWidget(row, self.COL_ACTION) is btn:
                self.step_table.removeRow(row)
                break
        self._update_total_hint()
        self._adjust_step_height()

    def _update_total_hint(self):
        total = 0
        total_time = 0.0
        interval = self.inp_interval.value()

        for r in range(self.step_table.rowCount()):
            cw = self.step_table.cellWidget(r, self.COL_COUNT)
            dw = self.step_table.cellWidget(r, self.COL_DURATION)
            if cw and dw:
                count = cw.value()
                duration = dw.value()
                total += count
                total_time += count * (duration + self.OBSERVATION_SEC)

        if total > 1:
            total_time += (total - 1) * (interval + self.RESET_TIME_SEC)

        self._total_plan = total
        self.lbl_total.setText(f"总次数：{total}")
        self.lbl_estimate.setText(
            f"预计：{self._fmt_duration(total_time)}" if total else "预计：—")

    # ══════════════════════════════════════════════════════════════
    # 计划展开
    # ══════════════════════════════════════════════════════════════
    def _collect_plan(self) -> list:
        plan = []
        cuff = self._base.get("cuff_type", PROTOCOL["cuff_type_ext"])
        for row in range(self.step_table.rowCount()):
            p = self.step_table.cellWidget(row, self.COL_PRESSURE).value()
            d = self.step_table.cellWidget(row, self.COL_DURATION).value()
            t = self.step_table.cellWidget(row, self.COL_THRESHOLD).value()
            c = self.step_table.cellWidget(row, self.COL_COUNT).value()
            for _ in range(c):
                plan.append({
                    "pressure":  p,
                    "duration":  d,
                    "threshold": t,
                    "cuff_type": cuff,
                })
        return plan

    # ══════════════════════════════════════════════════════════════
    # 清空曲线
    # ══════════════════════════════════════════════════════════════
    def _on_clear_chart(self):
        self.clear_chart_requested.emit()

    # ══════════════════════════════════════════════════════════════
    # 按钮
    # ══════════════════════════════════════════════════════════════
    def _on_start(self):
        if self._running:
            return
        plan = self._collect_plan()
        if not plan:
            return

        options = {
            "interval":     self.inp_interval.value(),
            "stop_on_fail": self.chk_stop.isChecked(),
        }

        self._running = True
        self._total_plan = len(plan)
        self.result_table.setRowCount(0)
        self.lbl_progress.setText(f"准备中 · 共 {self._total_plan} 次")

        self._set_batch_status("running")
        self.lbl_round.setText(f"0 / {self._total_plan}")
        self.lbl_pass.setText("✅ 0")
        self.lbl_fail.setText("❌ 0")

        from time import time as _now
        self._elapsed_t0 = _now()
        self.lbl_elapsed.setText("累计：0 秒")
        self._elapsed_timer.start()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setText("停止")
        self.step_table.setEnabled(False)
        self.btn_add_step.setEnabled(False)
        self.inp_interval.setEnabled(False)
        self.chk_stop.setEnabled(False)

        self.batch_started.emit(plan, options)

    def _on_cancel(self):
        if self._running:
            self.batch_stop_requested.emit()
        else:
            self.close()

    # ══════════════════════════════════════════════════════════════
    # MainWindow 回调
    # ══════════════════════════════════════════════════════════════
    def notify_test_started(self, index: int, total: int, params: dict):
        self.lbl_progress.setText(
            f"第 {index + 1} / {total} 次  ·  "
            f"压力 {params['pressure']} mmHg  ·  "
            f"时间 {params['duration']} s")
        self.lbl_round.setText(f"{index + 1} / {total}")

    def notify_test_result(self, index: int, result: dict):
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        self.result_table.setRowHeight(row, 36)

        ts     = datetime.now().strftime("%H:%M:%S")
        target = result.get("target_pressure", "—")
        stable = result.get("stable_pressure", "—")
        leak   = result.get("leak_rate", "—")
        ok     = result.get("qualified", False)
        tag    = "✅ 合格" if ok else "❌ 不合格"

        ALIGN = Qt.AlignmentFlag.AlignCenter

        def _mk(text: str) -> QTableWidgetItem:
            it = QTableWidgetItem(text)
            it.setTextAlignment(ALIGN)
            return it

        self.result_table.setItem(row, 0, _mk(str(index + 1)))
        self.result_table.setItem(row, 1, _mk(ts))
        self.result_table.setItem(row, 2, _mk(str(target)))
        self.result_table.setItem(
            row, 3, _mk(f"{stable:.1f}"
                        if isinstance(stable, (int, float))
                        else str(stable)))
        self.result_table.setItem(
            row, 4, _mk(f"{leak:.2f}"
                        if isinstance(leak, (int, float))
                        else str(leak)))
        self.result_table.setItem(row, 5, _mk(tag))

        self.result_table.scrollToBottom()

        n_all = self.result_table.rowCount()
        n_ok = sum(
            1 for r in range(n_all)
            if self.result_table.item(r, 5)
            and self.result_table.item(r, 5).text() == "✅ 合格"
        )
        self.lbl_pass.setText(f"✅ {n_ok}")
        self.lbl_fail.setText(f"❌ {n_all - n_ok}")

    def notify_batch_finished(self, reason: str):
        self._running = False
        self._elapsed_timer.stop()

        self.btn_start.setEnabled(True)
        self.btn_cancel.setText("关闭")
        self.step_table.setEnabled(True)
        self.btn_add_step.setEnabled(True)
        self.inp_interval.setEnabled(True)
        self.chk_stop.setEnabled(True)

        n_all = self.result_table.rowCount()
        n_ok = sum(
            1 for r in range(n_all)
            if self.result_table.item(r, 5)
            and self.result_table.item(r, 5).text() == "✅ 合格"
        )
        self.lbl_progress.setText(
            f"{reason}  ·  合格 {n_ok} / {n_all}  ·  "
            f"不合格 {n_all - n_ok} / {n_all}")

        if reason == "全部完成":
            self._set_batch_status("pass" if n_ok == n_all and n_all > 0 else "fail")
        else:
            self._set_batch_status("stopped")

    # ══════════════════════════════════════════════════════════════
    # 关窗
    # ══════════════════════════════════════════════════════════════
    def closeEvent(self, event):
        if self._running:
            self.batch_stop_requested.emit()
        super().closeEvent(event)