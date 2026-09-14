# -*- coding: utf-8 -*-
"""
about_dialog.py — "关于"对话框

独立模块，供 main_window 调用。
用法：
    from about_dialog import show_about
    show_about(self)          # self = 父窗口
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QFrame,
)

from config import COLORS as C


APP_NAME    = "Air Tightness Test  作者：得鹿梦鱼"
APP_VERSION = "v1.0"

# ── 正文内容（HTML）──────────────────────────────────────────
_ABOUT_HTML = f"""
<h2 style="margin:0 0 6px 0; color:{C['ink']};">
    {APP_NAME} · {APP_VERSION}
</h2>
<p style="margin:0 0 18px 0; color:{C['body_mid']}; font-size:13px;">
    配合有 JJG692-2010 标准的气密性测试仪使用，用于气密性测量的参数配置、实时监控与结果记录。
</p>

<h3 style="margin:0 0 6px 0; color:{C['ink']}; font-size:15px;">功能介绍</h3>
<ul style="margin:0 0 18px 18px; color:{C['body']}; font-size:13px; line-height:1.9;">
    <li><b>单次测试</b>：设定目标压力、稳压时间、合格阈值和袖带类型，
        一键执行完整测试流程（复位 → 充气 → 稳压 → 测试 → 泄气），实时绘制压力曲线。</li>
    <li><b>批量测试</b>：支持多压力档循环测试，每档可独立设置次数，
        自动生成对比曲线与合格率统计。</li>
    <li><b>数据记录</b>：测试结果与运行日志自动保存到程序目录下的
        <code>Test_Results/</code> 和 <code>Test_Logs/</code> 文件夹，
        CSV 格式兼容 Excel。</li>
    <li><b>设备管理</b>：支持串口自动识别、手动连接、模拟模式调试。</li>
</ul>

<h3 style="margin:0 0 6px 0; color:{C['ink']}; font-size:15px;">使用说明</h3>
<ol style="margin:0 0 6px 18px; color:{C['body']}; font-size:13px; line-height:1.9;">
    <li><b>连接设备</b>：菜单「设备 → 自动识别并连接」，或手动选择串口。</li>
    <li><b>单次测试</b>：在主界面设置参数 → 点击「开始测试」→
        观察曲线与状态 → 完成后自动保存结果。</li>
    <li><b>批量测试</b>：点击「批量测试」→ 添加压力档 →
        设置每档次数与间隔 → 点击「开始批量」。</li>
    <li><b>查看记录</b>：菜单「文件 → 打开测试结果 / 打开测试日志」直接定位文件夹。</li>
</ol>

<p style="margin:12px 0 0 0; color:{C['mute']}; font-size:12px;">
    界面右侧实时显示稳定压力与漏气率，测试完成后展示合格 / 不合格判定。
</p>
"""


class AboutDialog(QDialog):
    """独立"关于"对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        self.setModal(True)
        self.resize(560, 520)
        self.setMinimumSize(480, 400)
        self.setStyleSheet(f"QDialog {{ background: {C['canvas']}; }}")

        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # ── Eyebrow ──
        eb = QLabel("ABOUT")
        eb.setStyleSheet(
            f"color:{C['mute']}; font-size:12px; font-weight:500;")
        f = QFont()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        eb.setFont(f)
        lay.addWidget(eb)

        # ── 正文（可滚动）──
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setStyleSheet(
            f"QTextBrowser {{"
            f"  background:{C['canvas']};"
            f"  border:none;"
            f"  padding: 0;"
            f"  selection-background-color:{C['primary']};"
            f"  selection-color:{C['on_primary']}; }}")
        view.setHtml(_ABOUT_HTML)
        lay.addWidget(view, 1)

        # ── 底部按钮 ──
        btns = QHBoxLayout()
        btns.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("ButtonPrimary")
        btn_ok.setFixedHeight(40)
        btn_ok.setMinimumWidth(90)
        btn_ok.clicked.connect(self.accept)
        btns.addWidget(btn_ok)

        lay.addLayout(btns)


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════
def show_about(parent=None):
    """弹出"关于"对话框"""
    dlg = AboutDialog(parent)
    dlg.exec()