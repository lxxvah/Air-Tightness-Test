# -*- coding: utf-8 -*-
"""
main_window.py — 主界面

职责：
  · 串口 I/O（SerialWorker）
  · 单次测试执行（复位序列 → 状态机 → 结算）
  · 帧分发（曲线、进度、状态、日志）
  · 硬件收尾（退出PC / 断开串口）
  · 自动保存结果 / 日志（report_manager）

批量相关的 UI 与生命周期编排在 batch_test_dialog.py。
"""

import os
import time
from datetime import datetime
from about_dialog import show_about

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QProgressBar,
)

from config import (
    COLORS as C, PROTOCOL, TEST_DEFAULTS, TEST_RANGES,
    SERIAL_DEFAULTS, DEVICE_IDENTIFICATION as DEVID,
    TEST_RUNTIME,
)
from serial_worker import (
    SerialWorker, build_leak_test_command,
    build_reset, build_disconnect,
    find_device_ports, list_all_ports,
)
from serial_dialog import SerialDialog
from batch_test_dialog import BatchTestDialog
from batch_runner import BatchRunner
from pressure_chart import PressureChart
from simulator import TEST_SEC as SIM_OBSERVATION_SEC

import report_manager


# ═══════════════════════════════════════════════════════════════════
# 测试阶段
# ═══════════════════════════════════════════════════════════════════
STAGE_IDLE        = "idle"
STAGE_INFLATING   = "inflating"
STAGE_STABILIZING = "stabilizing"
STAGE_TESTING     = "testing"
STAGE_COMPLETED   = "completed"

_STAGE_UI = {
    STAGE_IDLE:        ("空闲",       C["mute_soft"]),
    STAGE_INFLATING:   ("充气中",     C["blue_info"]),
    STAGE_STABILIZING: ("稳压中",     C["blue_info"]),
    STAGE_TESTING:     ("测试中",     C["orange"]),
    STAGE_COMPLETED:   ("测试完成",   None),
}

CHART_STOP_PRESSURE = 0.1
RESET_STEP_WAIT_MS  = 200
SERIAL_FLUSH_WAIT_MS = 150


# ═══════════════════════════════════════════════════════════════════
# 通用小部件
# ═══════════════════════════════════════════════════════════════════

def eyebrow(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Eyebrow")
    f = QFont()
    f.setPixelSize(12)
    f.setWeight(QFont.Weight.Medium)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
    lbl.setFont(f)
    return lbl


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    f = QFont()
    f.setPixelSize(20)
    f.setWeight(QFont.Weight.Medium)
    lbl.setFont(f)
    return lbl


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {C['body_mid']}; font-size: 12px; font-weight: 500;")
    return lbl


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)


# ═══════════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Air Tightness Test  作者：得鹿梦鱼  「莫道桑榆晚，为霞尚满天」")
        self.resize(1440, 900)
        self.setMinimumSize(1120, 720)

        # 单次测试状态
        self._running              = False
        self._chart_running        = False
        self._serial_ready         = False
        self._use_simulation       = False
        self._pending_action       = None
        self._pending_test_params  = None
        self._t0                   = 0.0
        self._deadline             = 0.0
        self._threshold            = TEST_DEFAULTS["threshold"]

        # 状态机
        self._stage           = STAGE_IDLE
        self._target_pressure = float(TEST_DEFAULTS["pressure"])
        self._duration        = float(TEST_DEFAULTS["duration"])
        self._last_pressure   = 0.0
        self._stable_pressure = 0.0
        self._leak_rate       = 0.0
        self._total_time      = 0
        self._total_expected  = 0.0

        # 本轮曲线是否见过高压
        self._chart_seen_pressure = False

        # 批量
        self._batch_dialog       = None
        self._batch_runner       = None
        self._in_batch           = False
        self._pending_batch_plan = None

        # 时间戳 / 日志起点（自动保存用）
        self._test_start_dt         = None
        self._test_log_start_block  = 0
        self._batch_start_dt        = None
        self._batch_log_start_block = 0

        # 串口
        self.worker = SerialWorker(self)
        self.worker.connection_changed.connect(self._on_connection_changed)
        self.worker.frame_received.connect(self._on_frame_received)
        self.worker.error_occurred.connect(lambda msg: self._log(f"⚠ {msg}"))
        self.worker.raw_tx.connect(lambda d: self._log(f"TX → {d.hex().upper()}"))
        self.worker.raw_rx.connect(self._on_raw_rx)
        self.worker.start()

        self._build_menu()
        self._build_ui()
        self._build_timer()

        self._log("系统就绪，等待开始测试…")

    # ══════════════════════════════════════════════════════════════
    # 菜单栏
    # ══════════════════════════════════════════════════════════════
    def _build_menu(self):
        mb = self.menuBar()

        m_file = mb.addMenu("文件")
        m_file.addAction("新建测试", lambda: self._reset())
        m_file.addAction("打开测试日志", report_manager.open_logs_folder)
        m_file.addAction("打开测试结果", report_manager.open_results_folder)
        m_file.addSeparator()
        m_file.addAction("退出", self.close)

        m_dev = mb.addMenu("设备")
        m_dev.addAction("自动识别并连接", self._auto_detect_and_connect)
        m_dev.addSeparator()
        m_dev.addAction("连接串口…",    self._connect_serial)
        m_dev.addAction("断开串口",     self._disconnect_serial)
        m_dev.addSeparator()
        m_dev.addAction("模拟模式",     self._enable_simulation)
        m_dev.addAction("停止模拟",     self._disable_simulation)

        m_test = mb.addMenu("测试")
        m_test.addAction("开始测试", self._start)
        m_test.addAction("停止测试", self._stop)
        m_test.addSeparator()
        m_test.addAction("批量测试…", self._open_batch_dialog)

        m_help = mb.addMenu("帮助")
        m_help.addAction("关于", lambda: show_about(self))

    # ══════════════════════════════════════════════════════════════
    # 布局
    # ══════════════════════════════════════════════════════════════
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(20)

        body = QHBoxLayout()
        body.setSpacing(20)

        left = QVBoxLayout(); left.setSpacing(20)
        left.addWidget(self._card_params(), 0)
        left.addWidget(self._card_chart(), 1)
        left.addWidget(self._card_log(), 0)

        right = QVBoxLayout(); right.setSpacing(20)
        right.addWidget(self._card_actions(), 0)
        right.addWidget(self._card_status(), 0)
        right.addWidget(self._card_result(), 1)

        body.addLayout(left, 65)
        body.addLayout(right, 35)
        root.addLayout(body, 1)

    def _card_params(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        head = QHBoxLayout()
        head.addWidget(eyebrow("Parameters")); head.addSpacing(16)
        head.addWidget(section_title("参数设置")); head.addStretch()
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16); grid.setVerticalSpacing(6)

        self.inp_pressure = QSpinBox()
        self.inp_pressure.setRange(*TEST_RANGES["pressure"])
        self.inp_pressure.setValue(TEST_DEFAULTS["pressure"])
        self.inp_pressure.setSuffix("  mmHg")
        grid.addWidget(field_label("目标压力"), 0, 0)
        grid.addWidget(self.inp_pressure,       1, 0)

        self.inp_duration = QSpinBox()
        self.inp_duration.setRange(*TEST_RANGES["duration"])
        self.inp_duration.setValue(TEST_DEFAULTS["duration"])
        self.inp_duration.setSuffix("  s")
        grid.addWidget(field_label("稳压时间"), 0, 1)
        grid.addWidget(self.inp_duration,       1, 1)

        self.inp_threshold = QDoubleSpinBox()
        self.inp_threshold.setRange(*TEST_RANGES["threshold"])
        self.inp_threshold.setDecimals(2); self.inp_threshold.setSingleStep(0.1)
        self.inp_threshold.setValue(TEST_DEFAULTS["threshold"])
        self.inp_threshold.setSuffix("  mmHg/min")
        grid.addWidget(field_label("合格阈值"), 0, 2)
        grid.addWidget(self.inp_threshold,      1, 2)

        self.inp_cuff = QComboBox()
        self.inp_cuff.addItems(["外部袖带 (0x00)", "内部袖带 (0x01)"])
        grid.addWidget(field_label("袖带类型"), 0, 3)
        grid.addWidget(self.inp_cuff,           1, 3)

        for c in range(4):
            grid.setColumnStretch(c, 1)

        lay.addLayout(grid)
        return card

    def _card_chart(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(eyebrow("Live Chart")); head.addSpacing(16)
        head.addWidget(section_title("实时压力曲线")); head.addStretch()

        cap = QLabel("实时压力")
        cap.setStyleSheet(f"color: {C['mute']}; font-size: 12px;")
        head.addWidget(cap); head.addSpacing(8)

        self.lbl_live_pressure = QLabel("—")
        self.lbl_live_pressure.setStyleSheet(
            f"color: {C['ink']}; font-size: 26px; font-weight: 600;")
        head.addWidget(self.lbl_live_pressure)

        unit = QLabel("mmHg")
        unit.setStyleSheet(f"color: {C['mute']}; font-size: 12px; padding-bottom: 4px;")
        head.addWidget(unit, 0, Qt.AlignmentFlag.AlignBottom)

        lay.addLayout(head)
        self.chart = PressureChart()
        lay.addWidget(self.chart, 1)
        return card

    def _card_log(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(eyebrow("Console")); head.addSpacing(16)
        head.addWidget(section_title("日志")); head.addStretch()

        small_qss = (
            f"QPushButton {{ background:{C['canvas']}; color:{C['ink']};"
            f" border:1px solid {C['hairline']}; border-radius:4px;"
            f" font-size:12px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border-color:{C['ink']}; }}"
        )

        btn_clear = QPushButton("清空")
        btn_clear.setObjectName("ButtonSecondary")
        btn_clear.setFixedSize(70, 30)
        btn_clear.setStyleSheet(small_qss)
        btn_clear.clicked.connect(lambda: self.log_view.clear())
        head.addWidget(btn_clear)

        lay.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(170)
        self.log_view.setMaximumBlockCount(2000)
        lay.addWidget(self.log_view)
        return card

    def _card_actions(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(eyebrow("Control"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        # 行 0：开始测试 / 停止测试
        self.btn_start = QPushButton("开始测试")
        self.btn_start.setObjectName("ButtonPrimary")
        self.btn_start.setMinimumHeight(48)
        self.btn_start.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_start.clicked.connect(self._start)
        grid.addWidget(self.btn_start, 0, 0)

        self.btn_stop = QPushButton("停止测试")
        self.btn_stop.setObjectName("ButtonSecondary")
        self.btn_stop.setMinimumHeight(48)
        self.btn_stop.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        grid.addWidget(self.btn_stop, 0, 1)

        # 行 1：批量测试 / 打开测试结果
        self.btn_batch = QPushButton("批量测试")
        self.btn_batch.setObjectName("ButtonSecondary")
        self.btn_batch.setMinimumHeight(48)
        self.btn_batch.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_batch.clicked.connect(self._open_batch_dialog)
        grid.addWidget(self.btn_batch, 1, 0)

        self.btn_open_results = QPushButton("打开测试结果")
        self.btn_open_results.setObjectName("ButtonSecondary")
        self.btn_open_results.setMinimumHeight(48)
        self.btn_open_results.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_open_results.clicked.connect(report_manager.open_results_folder)
        grid.addWidget(self.btn_open_results, 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return card

    def _card_status(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)
        lay.addWidget(eyebrow("Status"))

        row = QHBoxLayout(); row.setSpacing(10)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.dot.setStyleSheet(f"background:{C['mute_soft']}; border-radius:5px;")

        self.lbl_status = QLabel("空闲")
        self.lbl_status.setStyleSheet(
            f"color:{C['ink']}; font-size:22px; font-weight:500;")
        row.addWidget(self.dot); row.addWidget(self.lbl_status); row.addStretch()
        lay.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100); self.progress.setValue(0)
        self.progress.setTextVisible(False); self.progress.setFixedHeight(6)
        lay.addWidget(self.progress)

        time_row = QHBoxLayout(); time_row.setSpacing(24)

        t1 = QVBoxLayout(); t1.setSpacing(2)
        t1.addWidget(field_label("已用时间"))
        self.lbl_elapsed = QLabel("0.0 s")
        self.lbl_elapsed.setStyleSheet(f"color:{C['ink']}; font-size:16px; font-weight:500;")
        t1.addWidget(self.lbl_elapsed)

        t2 = QVBoxLayout(); t2.setSpacing(2)
        t2.addWidget(field_label("预计总时长"))
        self.lbl_total = QLabel("—")
        self.lbl_total.setStyleSheet(f"color:{C['body_mid']}; font-size:16px; font-weight:500;")
        t2.addWidget(self.lbl_total)

        t3 = QVBoxLayout(); t3.setSpacing(2)
        t3.addWidget(field_label("实时泄气率"))
        self.lbl_live_leak = QLabel("—")
        self.lbl_live_leak.setStyleSheet(
            f"color:{C['ink']}; font-size:16px; font-weight:500;")
        t3.addWidget(self.lbl_live_leak)

        time_row.addLayout(t1)
        time_row.addLayout(t2)
        time_row.addLayout(t3)
        time_row.addStretch()
        lay.addLayout(time_row)
        return card

    def _card_result(self) -> QFrame:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(18)
        lay.addWidget(eyebrow("Result"))
        lay.addWidget(section_title("测试结果"))

        lay.addWidget(field_label("稳定压力"))
        row1 = QHBoxLayout(); row1.setSpacing(6)
        self.res_pressure = QLabel("—")
        self.res_pressure.setStyleSheet(
            f"color:{C['ink']}; font-size:32px; font-weight:600;")
        u1 = QLabel("mmHg")
        u1.setStyleSheet(f"color:{C['mute']}; font-size:13px; padding-bottom:5px;")
        row1.addWidget(self.res_pressure)
        row1.addWidget(u1, 0, Qt.AlignmentFlag.AlignBottom)
        row1.addStretch()
        lay.addLayout(row1)

        lay.addWidget(field_label("漏气率"))
        row2 = QHBoxLayout(); row2.setSpacing(6)
        self.res_leak = QLabel("—")
        self.res_leak.setStyleSheet(
            f"color:{C['ink']}; font-size:32px; font-weight:600;")
        u2 = QLabel("mmHg/min")
        u2.setStyleSheet(f"color:{C['mute']}; font-size:13px; padding-bottom:5px;")
        row2.addWidget(self.res_leak)
        row2.addWidget(u2, 0, Qt.AlignmentFlag.AlignBottom)
        row2.addStretch()
        lay.addLayout(row2)

        lay.addStretch()

        self.badge = QLabel("等待测试")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedHeight(48)
        self.badge.setStyleSheet(self._badge_qss("idle"))
        lay.addWidget(self.badge)
        return card

    @staticmethod
    def _badge_qss(state: str) -> str:
        if state == "pass":
            bg, fg = C["green"], C["primary"]
        elif state == "fail":
            bg, fg = C["red"], C["on_primary"]
        elif state == "running":
            bg, fg = "#f2f2f2", C["ink"]
        else:
            bg, fg = "#f5f5f5", C["mute"]
        return (f"background-color:{bg}; color:{fg};"
                f" border-radius:6px; font-size:15px; font-weight:600;"
                f" letter-spacing:0.5px;")

    def _set_badge(self, state: str, text: str = None):
        self.badge.setStyleSheet(self._badge_qss(state))
        if text is None:
            text = {"pass": "✅  合格", "fail": "❌  不合格",
                    "running": "●  运行中", "idle": "等待测试"}[state]
        self.badge.setText(text)

    def _update_stage_ui(self, stage: str):
        text, color = _STAGE_UI.get(stage, ("空闲", C["mute_soft"]))
        self.lbl_status.setText(text)
        if color:
            self.dot.setStyleSheet(f"background:{color}; border-radius:5px;")
            self.lbl_status.setStyleSheet(
                f"color:{color}; font-size:22px; font-weight:500;")

    # ══════════════════════════════════════════════════════════════
    # UI 时钟
    # ══════════════════════════════════════════════════════════════
    def _build_timer(self):
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        if not self._running:
            return
        now = time.time()
        if self._deadline > 0 and now > self._deadline:
            self._abort("测试超时（设备未在规定时间内完成流程）")
            return
        elapsed = now - self._t0
        self.lbl_elapsed.setText(f"{elapsed:.1f} s")

    # ══════════════════════════════════════════════════════════════
    # 状态机
    # ══════════════════════════════════════════════════════════════
    def _classify_stage(self, frame: dict) -> str:
        tt     = frame["total_time"]
        p      = frame["pressure"]
        status = frame["status"]

        if status == PROTOCOL["status_complete"]:
            return STAGE_COMPLETED
        if tt == 0:
            if p >= self._target_pressure * 0.95:
                return STAGE_STABILIZING
            return STAGE_INFLATING
        elif tt <= self._duration:
            return STAGE_STABILIZING
        else:
            return STAGE_TESTING

    def _update_test_stage(self, frame: dict):
        new_stage = self._classify_stage(frame)
        if new_stage == self._stage:
            return
        self._stage = new_stage
        self._update_stage_ui(new_stage)

        if new_stage == STAGE_STABILIZING:
            self._log(f"▶ 进入稳压阶段（稳压时间 {self._duration:.0f}s）")
        elif new_stage == STAGE_TESTING:
            obs = TEST_RUNTIME["observation_sec"]
            self._log(f"▶ 稳压完成，进入测试阶段（观察期 {obs}s）")

    def _format_frame_log(self, frame: dict) -> str:
        stage = self._stage
        tt    = frame["total_time"]

        if stage == STAGE_INFLATING:
            label = "充气中"; time_text = ""
        elif stage == STAGE_STABILIZING:
            label = "稳压中"; time_text = f"稳压时间={tt:.0f}s"
        elif stage == STAGE_TESTING:
            label = "测试中"; time_text = f"测试时间={tt - self._duration:.0f}s"
        elif stage == STAGE_COMPLETED:
            label = "测试完成"; time_text = f"测试时间={tt - self._duration:.0f}s"
        else:
            label = frame["status_name"]; time_text = f"总时间={tt}s"

        return (f"   ↳ 压力={frame['pressure']:7.2f} mmHg  "
                f"状态={label:<4}  "
                f"稳定压={frame['stable_pressure']:6.2f}  "
                f"泄气率={frame['leak_rate']:5.2f} mmHg/min  "
                f"{time_text}")

    # ══════════════════════════════════════════════════════════════
    # 单次测试入口
    # ══════════════════════════════════════════════════════════════
    def _precheck(self) -> bool:
        if self._running or self._pending_test_params is not None:
            self._log("⚠ 已有测试在进行中"); return False
        if self.inp_pressure.value() <= 0:
            self._log("⚠ 目标压力必须大于 0"); return False
        if self.inp_duration.value() <= 0:
            self._log("⚠ 稳压时间必须大于 0"); return False
        self._log("▶ 前置检查通过")
        return True

    def _ensure_device(self, action: str) -> bool:
        if self._use_simulation:
            self._log("▶ 数据源：模拟模式"); return True
        if self._serial_ready:
            self._log("▶ 数据源：串口已就绪"); return True
        self._log("▶ 未检测到串口连接，自动识别中…")
        self._pending_action = action
        self._auto_detect_and_connect()
        return False

    def _do_start(self):
        params = self._collect_params()
        if self._use_simulation:
            self.worker.start_simulation(params["pressure"], params["duration"])
            self._start_test_run(params)
        else:
            self._start_test_with_reset(params)

    def _start_test_with_reset(self, params: dict):
        self._pending_test_params = dict(params)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._log("─" * 46)
        self._log("▶ 复位设备 · 断开连接")
        self.worker.send(build_disconnect())
        QTimer.singleShot(RESET_STEP_WAIT_MS, self._step_reset)

    def _step_reset(self):
        if self._pending_test_params is None:
            return
        self._log("▶ 复位设备 · 初始化")
        self.worker.send(build_reset())
        QTimer.singleShot(RESET_STEP_WAIT_MS, self._step_send_test)

    def _step_send_test(self):
        params = self._pending_test_params
        if params is None:
            return
        self._pending_test_params = None
        self._start_test_run(params)

    def _start_test_run(self, params: dict):
        target    = params["pressure"]
        duration  = params["duration"]
        threshold = params["threshold"]
        cuff      = params["cuff_type"]

        is_batch_round = params.get("_batch_index") is not None
        keep_chart = is_batch_round and self.chart.has_data()

        self._reset(keep_chart=keep_chart)
        self._running        = True
        self._chart_running  = True
        self._t0             = time.time()
        self._threshold      = threshold
        self._chart_seen_pressure = False

        # 记录测试开始时刻 / 日志起点
        self._test_start_dt        = datetime.now()
        self._test_log_start_block = self.log_view.blockCount()

        self._stage           = STAGE_INFLATING
        self._target_pressure = float(target)
        self._duration        = float(duration)
        self._last_pressure   = 0.0
        self._stable_pressure = 0.0
        self._leak_rate       = 0.0
        self._total_time      = 0

        obs = params.get("observation_sec")
        if obs is None:
            obs = (SIM_OBSERVATION_SEC if self._use_simulation
                   else TEST_RUNTIME["observation_sec"])

        self._total_expected = self._duration + obs
        self._deadline = (self._t0
                          + self._total_expected
                          + TEST_RUNTIME["timeout_margin"])

        if is_batch_round:
            self._batch_round_ended = False

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        if keep_chart:
            self.chart.start_round(target)
        else:
            self.chart.start(target)
        self.chart.set_target_visible(True)

        self.progress.setValue(0)
        self._set_badge("running")
        self._update_stage_ui(STAGE_INFLATING)
        self.lbl_live_leak.setText("—")
        self.lbl_total.setText(f"{self._total_expected:.0f} s")

        idx = params.get("_batch_index")
        prefix = f"[#{idx + 1}] " if idx is not None else ""
        self._log("─" * 46)
        self._log(f"▶ {prefix}开始气密性测试")
        self._log(f"   目标压力 : {target} mmHg")
        self._log(f"   稳压时间 : {duration} s")
        self._log(f"   观察期   : {TEST_RUNTIME['observation_sec']} s")
        self._log(f"   合格阈值 : {threshold:.2f} mmHg/min")

        cmd = build_leak_test_command(target, duration, cuff)
        self.worker.send(cmd)
        self.timer.start()

    # ══════════════════════════════════════════════════════════════
    # 帧入口
    # ══════════════════════════════════════════════════════════════
    def _on_raw_rx(self, data: bytes):
        self._log(f"RX ← {data.hex().upper()}")

    def _on_frame_received(self, frame: dict):
        if self._pending_test_params is not None:
            return

        if self._chart_running:
            p = frame["pressure"]
            self.chart.push(p)
            self.lbl_live_pressure.setText(f"{p:.1f}")
            if p > CHART_STOP_PRESSURE:
                self._chart_seen_pressure = True
            if self._chart_seen_pressure and p <= CHART_STOP_PRESSURE:
                self._chart_running = False
                self.chart.stop()
                self._log(f"▶ 压力降至 {p:.2f} mmHg，曲线停止绘图")
                self._on_round_chart_stopped()

        if self._running:
            self._update_test_stage(frame)

        self.lbl_live_leak.setText(f"{frame['leak_rate']:.2f} mmHg/min")

        tt = frame["total_time"]
        if self._total_expected > 0:
            pct = min(100, int(tt / self._total_expected * 100))
            self.progress.setValue(pct)

        self._log(self._format_frame_log(frame))

        if frame["status"] == PROTOCOL["status_complete"] and self._running:
            self._finish_with_result(frame)

        if frame["status"] == PROTOCOL["status_failed"] and self._running:
            self._abort("设备上报测量失败")

    # ══════════════════════════════════════════════════════════════
    # 结算
    # ══════════════════════════════════════════════════════════════
    def _finish_with_result(self, frame: dict):
        self._running  = False
        self._deadline = 0.0
        self._stage    = STAGE_COMPLETED
        self.timer.stop()

        if not self._in_batch:
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

        stable     = frame.get("stable_pressure", 0.0)
        leak       = frame.get("leak_rate", 0.0)
        total_time = frame.get("total_time", 0)

        self._stable_pressure = stable
        self._leak_rate       = leak
        self._total_time      = total_time

        threshold = getattr(self, "_threshold", self.inp_threshold.value())
        qualified = leak < threshold

        self.res_pressure.setText(f"{stable:.2f}")
        self.res_leak.setText(f"{leak:.2f}")
        self.progress.setValue(100)

        self.dot.setStyleSheet(
            f"background:{C['green'] if qualified else C['red']}; border-radius:5px;")
        self.lbl_status.setText("测试完成")
        self.lbl_status.setStyleSheet(
            f"color:{C['ink']}; font-size:22px; font-weight:500;")
        self._set_badge("pass" if qualified else "fail")

        self._log("─" * 46)
        self._log("✔ 测试完成")
        self._log(f"   总测量时间 : {total_time} s")
        self._log(f"   稳定压力   : {stable:.2f} mmHg")
        self._log(f"   漏气率     : {leak:.2f} mmHg/min")
        self._log(f"   判定       : {'✅ 合格' if qualified else '❌ 不合格'}"
                  f"（阈值 {threshold:.2f}）")

        if self._in_batch and self._batch_runner and self._batch_runner.active:
            self._batch_runner.on_test_finished({
                "stable_pressure": stable,
                "leak_rate":       leak,
                "qualified":       qualified,
                "raw":             frame.get("raw", b""),
            })

        if not self._chart_running:
            self._on_round_chart_stopped()

        # 单次测试（非批量）完成后自动保存
        if not self._in_batch:
            self._auto_save_single()

    # ══════════════════════════════════════════════════════════════
    # 自动保存
    # ══════════════════════════════════════════════════════════════
    def _auto_save_single(self):
        """测试完成后自动写入结果 CSV + 日志 LOG"""
        if self._test_start_dt is None:
            return
        try:
            cuff_name = ("外部袖带" if self.inp_cuff.currentIndex() == 0
                         else "内部袖带")
            qualified = self._leak_rate < self._threshold

            result_path = report_manager.save_single_result(
                self._test_start_dt,
                int(self._target_pressure),
                int(self._duration),
                self._threshold,
                cuff_name,
                self._stable_pressure,
                self._leak_rate,
                self._total_time,
                qualified,
            )
            log_text = self._get_log_since(self._test_log_start_block)
            log_path = report_manager.save_single_log(
                self._test_start_dt,
                int(self._target_pressure),
                int(self._duration),
                log_text,
            )
            self._log(f"✔ 结果已保存：{os.path.basename(result_path)}")
            self._log(f"✔ 日志已保存：{os.path.basename(log_path)}")
        except Exception as e:
            self._log(f"✘ 自动保存失败：{e}")

    def _auto_save_batch(self):
        """批量结束后自动写入结果 CSV + 日志 LOG"""
        if self._batch_start_dt is None or self._batch_dialog is None:
            return
        try:
            tbl = self._batch_dialog.step_table
            plan_rows = []
            for row in range(tbl.rowCount()):
                p = tbl.cellWidget(row, self._batch_dialog.COL_PRESSURE).value()
                d = tbl.cellWidget(row, self._batch_dialog.COL_DURATION).value()
                t = tbl.cellWidget(row, self._batch_dialog.COL_THRESHOLD).value()
                c = tbl.cellWidget(row, self._batch_dialog.COL_COUNT).value()
                plan_rows.append((p, d, f"{t:.2f}", c))

            rtb = self._batch_dialog.result_table
            result_rows = []
            for row in range(rtb.rowCount()):
                cells = []
                for col in range(rtb.columnCount()):
                    item = rtb.item(row, col)
                    cells.append(item.text() if item else "")
                result_rows.append(cells)

            result_path = report_manager.save_batch_result(
                self._batch_start_dt, plan_rows, result_rows)

            log_text = self._get_log_since(self._batch_log_start_block)
            log_path = report_manager.save_batch_log(
                self._batch_start_dt, log_text)

            self._log(f"✔ 结果已保存：{os.path.basename(result_path)}")
            self._log(f"✔ 日志已保存：{os.path.basename(log_path)}")
        except Exception as e:
            self._log(f"✘ 自动保存失败：{e}")

    def _get_log_since(self, start_block: int) -> str:
        """取 log_view 从 start_block 起的所有文本"""
        doc = self.log_view.document()
        end_block = doc.blockCount()
        if end_block <= start_block:
            return ""
        return "\n".join(
            doc.findBlockByNumber(i).text()
            for i in range(start_block, end_block)
        )

    # ══════════════════════════════════════════════════════════════
    # 硬件收尾
    # ══════════════════════════════════════════════════════════════
    def _send_exit_pc(self, reason: str = "") -> bool:
        if self._use_simulation or not self._serial_ready:
            return False
        suffix = f"（{reason}）" if reason else ""
        self._log(f"■ 发送：退出PC (00 00 00 00 00 00 00 00){suffix}")
        self.worker.send(build_disconnect())
        return True

    def _disconnect_serial_port(self, reason: str = "") -> bool:
        if not self._serial_ready:
            return False
        suffix = f"（{reason}）" if reason else ""
        self._log(f"■ 断开串口连接{suffix}")
        self.worker.disconnect_port()
        return True

    def _flush_serial_commands(self) -> None:
        if self._use_simulation or not self._serial_ready:
            return
        time.sleep(SERIAL_FLUSH_WAIT_MS / 1000.0)

    def _shutdown_hardware(self, reason: str = "关闭窗口") -> None:
        if self._send_exit_pc(reason):
            self._flush_serial_commands()
        if self._disconnect_serial_port(reason):
            self._flush_serial_commands()

    # ══════════════════════════════════════════════════════════════
    # 停止 / 中止 / 复位
    # ══════════════════════════════════════════════════════════════
    def _abort(self, reason: str):
        if not self._running and self._pending_test_params is None:
            return
        self._pending_test_params = None
        self._terminate(reason)

    def _stop(self):
        if self._in_batch:
            self._on_batch_stop_requested()
            self._shutdown_hardware("批量测试已停止")
            return
        if not self._running and self._pending_test_params is None:
            return
        self._pending_test_params = None
        self._terminate("测试被用户停止")
        self._send_exit_pc("测试已停止")

    def _terminate(self, reason: str):
        self._running       = False
        self._chart_running = False
        self._deadline      = 0.0
        self._stage         = STAGE_IDLE
        self.timer.stop()
        self.chart.stop()
        self.worker.stop_simulation()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._update_stage_ui(STAGE_IDLE)
        self.lbl_live_leak.setText("—")
        self._set_badge("idle", "已停止")
        self._log(f"■ {reason}")

    def _reset(self, keep_chart: bool = False):
        self.res_pressure.setText("—")
        self.res_leak.setText("—")
        self.progress.setValue(0)
        self.lbl_elapsed.setText("0.0 s")
        self.lbl_live_pressure.setText("—")
        self.lbl_live_leak.setText("—")
        self.lbl_total.setText("—")
        self._stage = STAGE_IDLE
        self._chart_running = False
        self._update_stage_ui(STAGE_IDLE)
        self._set_badge("idle")
        if not keep_chart:
            self.chart.stop()
            self.chart.clear()

    # ══════════════════════════════════════════════════════════════
    # 入口按钮
    # ══════════════════════════════════════════════════════════════
    def _start(self):
        if self._in_batch:
            self._log("⚠ 批量测试进行中，无法启动单次测试"); return
        if not self._precheck():
            return
        if self._ensure_device("single"):
            self._do_start()

    def _collect_params(self) -> dict:
        return {
            "pressure":  self.inp_pressure.value(),
            "duration":  self.inp_duration.value(),
            "threshold": self.inp_threshold.value(),
            "cuff_type": PROTOCOL["cuff_type_ext"]
                         if self.inp_cuff.currentIndex() == 0
                         else PROTOCOL["cuff_type_int"],
        }

    # ══════════════════════════════════════════════════════════════
    # 数据源切换
    # ══════════════════════════════════════════════════════════════
    def _connect_serial(self):
        dlg = SerialDialog(self)
        if dlg.exec() != SerialDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        if not vals:
            return
        port, baud = vals
        self._use_simulation = False
        self._log(f"尝试连接 {port} @ {baud} …")
        self.worker.connect_port(port=port, baudrate=baud)

    def _disconnect_serial(self):
        self._use_simulation = False
        self.worker.disconnect_port()

    def _auto_detect_and_connect(self):
        self._log("🔍 自动识别串口设备 …")
        ports = find_device_ports()
        source = "VID/PID"
        if not ports and DEVID["FALLBACK_SCAN_ALL"]:
            ports = list_all_ports()
            source = "回退扫描"

        if not ports:
            self._log("✘ 未找到可用串口设备")
            action = self._pending_action
            if action:
                self._pending_action = None
                if action == "single":
                    self._log("⚠ 自动连接失败，测试中止")
                elif action == "batch":
                    pending = self._pending_batch_plan
                    self._pending_batch_plan = None
                    self._in_batch = False
                    if pending and self._batch_dialog:
                        self._batch_dialog.notify_batch_finished("连接失败")
                    self._log("⚠ 自动连接失败，批量测试中止")
            return

        port = ports[0]
        baud = SERIAL_DEFAULTS["baudrate"]
        self._use_simulation = False
        self._log(f"✔ 识别到 {port}（{source}），正在连接 {baud} …")
        self.worker.connect_port(port=port, baudrate=baud)

    def _enable_simulation(self):
        self._use_simulation = True
        self._log("✔ 数据源切换为：模拟模式")

    def _disable_simulation(self):
        self._use_simulation = False
        self.worker.stop_simulation()
        self._log("✔ 数据源切换为：真实串口")

    def _on_connection_changed(self, connected: bool, msg: str):
        self._log(("✔ " if connected else "✘ ") + msg)
        self._serial_ready = connected

        action = self._pending_action
        if action is None:
            return
        self._pending_action = None

        if not connected:
            if action == "single":
                self._log("⚠ 自动连接失败，测试中止")
            elif action == "batch":
                pending = self._pending_batch_plan
                self._pending_batch_plan = None
                self._in_batch = False
                if pending and self._batch_dialog:
                    self._batch_dialog.notify_batch_finished("连接失败")
                self._log("⚠ 自动连接失败，批量测试中止")
            return

        if action == "single":
            self._do_start()
        elif action == "batch":
            pending = self._pending_batch_plan
            self._pending_batch_plan = None
            if pending:
                self._begin_batch(*pending)

    # ══════════════════════════════════════════════════════════════
    # 批量测试
    # ══════════════════════════════════════════════════════════════
    def _open_batch_dialog(self):
        if self._in_batch:
            self._log("⚠ 批量测试进行中")
            return
        if self._batch_dialog and self._batch_dialog.isVisible():
            self._batch_dialog.raise_()
            return

        self._batch_dialog = BatchTestDialog(self._collect_params(), self)
        self._batch_dialog.batch_started.connect(self._on_batch_started)
        self._batch_dialog.batch_stop_requested.connect(
            self._on_batch_stop_requested)
        self._batch_dialog.clear_chart_requested.connect(
            self._on_clear_chart_from_batch)
        self._batch_dialog.finished.connect(self._on_batch_closed)
        self._batch_dialog.show()

    def _on_clear_chart_from_batch(self):
        """批量对话框请求清空曲线"""
        self.chart.stop()
        self.chart.clear()
        self._chart_running = False
        self._chart_seen_pressure = False
        self.lbl_live_pressure.setText("—")
        self._log("■ 曲线已清空")

    def _on_batch_started(self, plan: list, options: dict):
        if self._in_batch:
            self._log("⚠ 批量测试已在进行中")
            return
        if not plan:
            self._log("⚠ 批量计划为空")
            if self._batch_dialog:
                self._batch_dialog.notify_batch_finished("无任务")
            return

        self._in_batch = True

        # 记录批量开始时刻 / 日志起点
        self._batch_start_dt        = datetime.now()
        self._batch_log_start_block = self.log_view.blockCount()

        if not self._ensure_device("batch"):
            self._pending_batch_plan = (plan, options)
            return
        self._begin_batch(plan, options)

    def _begin_batch(self, plan: list, options: dict):
        if not self._use_simulation:
            self._log("▶ 批量启动复位 · 断开连接")
            self.worker.send(build_disconnect())
            QTimer.singleShot(RESET_STEP_WAIT_MS, lambda:
                              self._begin_batch_step2(plan, options))
        else:
            self._begin_batch_step2(plan, options)

    def _begin_batch_step2(self, plan: list, options: dict):
        if not self._use_simulation:
            self._log("▶ 批量启动复位 · 初始化")
            self.worker.send(build_reset())
            QTimer.singleShot(RESET_STEP_WAIT_MS, lambda:
                              self._begin_batch_final(plan, options))
        else:
            self._begin_batch_final(plan, options)

    def _begin_batch_final(self, plan: list, options: dict):
        if self._batch_runner is None:
            self._batch_runner = BatchRunner(self)
            self._batch_runner.test_requested.connect(self._start_batch_round)
            self._batch_runner.test_started.connect(self._on_batch_test_started)
            self._batch_runner.test_finished.connect(self._on_batch_test_finished)
            self._batch_runner.batch_finished.connect(self._on_batch_finished)
            self._batch_runner.log.connect(self._log)

        self._batch_runner.start(plan, options)

    def _on_batch_test_started(self, current: int, total: int, params: dict):
        if self._batch_dialog and self._batch_dialog.isVisible():
            self._batch_dialog.notify_test_started(current, total, params)

    def _on_batch_test_finished(self, index: int, result: dict):
        if not (self._batch_dialog and self._batch_dialog.isVisible()):
            return
        target = (self._batch_runner.get_params(index).get("pressure", 0)
                  if self._batch_runner else 0)
        self._batch_dialog.notify_test_result(index, {**result,
                                                     "target_pressure": target})

    def _on_batch_finished(self, reason: str):
        self._in_batch = False
        self._pending_batch_plan = None
        self._pending_test_params = None

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        if reason != "全部完成":
            self._running = False
            self._chart_running = False
            self._deadline = 0.0
            self._stage = STAGE_IDLE
            self.timer.stop()
            self.chart.stop()
            self.worker.stop_simulation()
            self._update_stage_ui(STAGE_IDLE)
            self._set_badge("idle", "已停止")

        if self._batch_dialog and self._batch_dialog.isVisible():
            self._batch_dialog.notify_batch_finished(reason)

        # 批量结束后自动保存结果 + 日志
        self._auto_save_batch()

    def _on_batch_stop_requested(self):
        if not self._in_batch:
            return
        self._pending_test_params = None
        if self._running:
            self._running = False
            self._chart_running = False
            self._deadline = 0.0
            self._stage = STAGE_IDLE
            self.timer.stop()
            self.chart.stop()
            self.worker.stop_simulation()
        if self._batch_runner:
            self._batch_runner.abort("用户中止批量测试")

    def _start_batch_round(self, params: dict):
        idx = params.get("_batch_index", 0)
        if idx == 0 or self._use_simulation or not self._serial_ready:
            self._start_test_run(params)
        else:
            self._start_test_with_reset(params)

    def _on_round_chart_stopped(self):
        if self._batch_runner and self._batch_runner.active:
            self._batch_runner.on_round_ended()

    def _on_batch_closed(self, _):
        if self._in_batch:
            self._on_batch_stop_requested()
        self._batch_dialog = None

    # ══════════════════════════════════════════════════════════════
    # 日志 / 退出
    # ══════════════════════════════════════════════════════════════
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}]  {msg}")

    def closeEvent(self, event):
        try:
            self._pending_test_params = None
            if self._in_batch:
                self._on_batch_stop_requested()
            self._shutdown_hardware("关闭窗口")
            self.worker.shutdown()
            self.worker.wait(1500)
        except Exception:
            pass
        super().closeEvent(event)