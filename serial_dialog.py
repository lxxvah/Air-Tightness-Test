# -*- coding: utf-8 -*-
"""
serial_dialog.py — 串口连接配置对话框

布局：
  · 顶栏：SERIAL CONNECTION + 连接串口（同一行）
  · 表单：串口号 [下拉] [刷新]
         波特率 [下拉] [自动识别]
  · 底部：取消 / 连接（都靠右，高度与输入框一致）

功能：
  · 列出全部串口
  · 按 VID/PID 自动识别设备（不做协议探测）
  · 返回 (port, baudrate)
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QComboBox, QPushButton, QLabel, QMessageBox,
)

from config import COLORS as C, SERIAL_DEFAULTS, DEVICE_IDENTIFICATION as DEVID

try:
    from serial.tools import list_ports
    HAS_PYSERIAL = True
except ImportError:
    list_ports = None
    HAS_PYSERIAL = False


class SerialDialog(QDialog):
    """返回 (port, baudrate) 的串口配置对话框"""

    BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

    # 输入框 / 按钮的统一高度
    ROW_HEIGHT = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连接串口")
        self.setModal(True)
        self.resize(480, 250)
        self.setStyleSheet(f"QDialog {{ background: {C['canvas']}; }}")

        self._result = None   # (port, baudrate)
        self._build_ui()
        self._refresh_ports()

    # ── 统一按钮样式（紧凑 padding，适应 36px 高）─────────
    def _compact_secondary_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background:{C['canvas']}; color:{C['ink']};"
            f"  border:1px solid {C['hairline']}; border-radius:4px;"
            f"  padding: 0 16px; font-size:13px; font-weight:500; }}"
            f"QPushButton:hover {{ border-color:{C['ink']}; }}"
            f"QPushButton:pressed {{ background:#f5f5f5; }}")

    def _compact_primary_qss(self) -> str:
        return (
            f"QPushButton {{"
            f"  background:{C['primary']}; color:{C['on_primary']};"
            f"  border:none; border-radius:4px;"
            f"  padding: 0 20px; font-size:14px; font-weight:500; }}"
            f"QPushButton:hover {{ background:{C['ink_strong']}; }}"
            f"QPushButton:pressed {{ background:#000000; }}")

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        # ── 顶栏：SERIAL CONNECTION + 连接串口 ──
        head = QHBoxLayout()
        head.setSpacing(16)

        eb = QLabel("SERIAL CONNECTION")
        eb.setStyleSheet(f"color:{C['mute']}; font-size:12px; font-weight:500;")
        f = QFont(); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        eb.setFont(f)
        head.addWidget(eb)

        title = QLabel("连接串口")
        title.setStyleSheet(f"color:{C['ink']}; font-size:20px; font-weight:500;")
        head.addWidget(title)

        head.addStretch()
        lay.addLayout(head)

        # ── 表单（Grid：标签 / 输入框 / 按钮）──
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 56)   # 标签列宽

        # 行 0：串口号 + 刷新
        grid.addWidget(self._mk_label("串口号"), 0, 0)

        self.cmb_port = QComboBox()
        self.cmb_port.setFixedHeight(self.ROW_HEIGHT)
        grid.addWidget(self.cmb_port, 0, 1)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedHeight(self.ROW_HEIGHT)
        self.btn_refresh.setStyleSheet(self._compact_secondary_qss())
        self.btn_refresh.clicked.connect(self._refresh_ports)
        grid.addWidget(self.btn_refresh, 0, 2)

        # 行 1：波特率 + 自动识别
        grid.addWidget(self._mk_label("波特率"), 1, 0)

        self.cmb_baud = QComboBox()
        self.cmb_baud.setFixedHeight(self.ROW_HEIGHT)
        self.cmb_baud.addItems([str(b) for b in self.BAUDRATES])
        self.cmb_baud.setCurrentText(str(SERIAL_DEFAULTS["baudrate"]))
        grid.addWidget(self.cmb_baud, 1, 1)

        self.btn_auto = QPushButton("自动识别")
        self.btn_auto.setFixedHeight(self.ROW_HEIGHT)
        self.btn_auto.setStyleSheet(self._compact_secondary_qss())
        self.btn_auto.clicked.connect(self._auto_detect)
        grid.addWidget(self.btn_auto, 1, 2)

        grid.setColumnStretch(1, 1)   # 输入框列吸收剩余宽度
        lay.addLayout(grid)

        lay.addStretch()

        # ── 底部按钮（靠右）──
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setFixedHeight(self.ROW_HEIGHT)
        self.btn_cancel.setStyleSheet(self._compact_secondary_qss())
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton("连接")
        self.btn_ok.setFixedHeight(self.ROW_HEIGHT)
        self.btn_ok.setStyleSheet(self._compact_primary_qss())
        self.btn_ok.clicked.connect(self._accept)
        btns.addWidget(self.btn_ok)

        lay.addLayout(btns)

    @staticmethod
    def _mk_label(text: str) -> QLabel:
        lbl = QLabel(text)
        # 字号与输入框一致（14px）
        lbl.setStyleSheet(
            f"color:{C['body_mid']}; font-size:14px; font-weight:500;")
        return lbl

    # ── 串口枚举 ─────────────────────────────────────────
    def _refresh_ports(self):
        self.cmb_port.clear()
        if not HAS_PYSERIAL or list_ports is None:
            self.cmb_port.addItem("（未安装 pyserial）")
            self.cmb_port.setEnabled(False)
            return
        self.cmb_port.setEnabled(True)
        ports = list_ports.comports()
        if not ports:
            self.cmb_port.addItem(SERIAL_DEFAULTS["port"])   # 至少给个默认
        else:
            for p in ports:
                label = (f"{p.device}  —  {p.description}"
                         if p.description else p.device)
                self.cmb_port.addItem(label, p.device)

    # ── 自动识别（按 VID/PID 定位，不做协议探测）───────
    def _auto_detect(self):
        from serial_worker import find_device_ports, list_all_ports

        ports = find_device_ports()
        source = "VID/PID"
        if not ports and DEVID["FALLBACK_SCAN_ALL"]:
            ports = list_all_ports()
            source = "回退扫描"

        if not ports:
            QMessageBox.information(self, "自动识别", "未找到可用串口设备")
            return

        target = ports[0]

        self._refresh_ports()
        selected = False
        for i in range(self.cmb_port.count()):
            data = self.cmb_port.itemData(i)
            text = self.cmb_port.itemText(i)
            if data == target or text.startswith(target):
                self.cmb_port.setCurrentIndex(i)
                selected = True
                break
        if not selected:
            self.cmb_port.insertItem(0, target, target)
            self.cmb_port.setCurrentIndex(0)

        extra = f"（{source}）" if source == "回退扫描" else ""
        QMessageBox.information(
            self, "自动识别",
            f"已选中 {target}{extra}\n点击「连接」完成连接")

    # ── 确认 ─────────────────────────────────────────────
    def _accept(self):
        if not HAS_PYSERIAL:
            QMessageBox.warning(self, "无法连接",
                                "请先安装 pyserial：pip install pyserial")
            return
        port = self.cmb_port.currentData()
        if not port:
            port = self.cmb_port.currentText().split()[0]
        if not port:
            QMessageBox.warning(self, "无法连接", "请选择一个串口")
            return
        baud = int(self.cmb_baud.currentText())
        self._result = (port, baud)
        self.accept()

    def values(self):
        """返回 (port, baudrate) 或 None"""
        return self._result