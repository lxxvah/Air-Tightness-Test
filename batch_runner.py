# -*- coding: utf-8 -*-
"""
batch_runner.py — 批量测试执行器（纯逻辑，无 UI / 无串口依赖）

职责：
  · 持有展开后的扁平任务队列 plan
  · 逐个请求执行，跟踪 current 索引
  · 每次结果返回后，等待"本轮彻底结束"再启动下一轮
  · 通过 Qt 信号把进度和结果广播出去

设计：
  · 只发"请求"和"通知"，从不主动调用 UI
  · 每轮启动时机由 MainWindow 通过 on_round_ended() 通知
  · 兜底：SETTLE_TIMEOUT_MS 内未收到通知则强制进入下一轮
"""

from PySide6.QtCore import QObject, QTimer, Signal


# 本轮收尾兜底超时（毫秒）：超过此时长未收到 on_round_ended，强制进下一轮
SETTLE_TIMEOUT_MS = 30000


class BatchRunner(QObject):
    """批量测试执行器"""

    # ── 出：请求 MainWindow 执行一次单次测试 ──
    test_requested = Signal(dict)              # params

    # ── 出：通知进度 ──
    test_started   = Signal(int, int, dict)    # current, total, params
    test_finished  = Signal(int, dict)         # index, result
    batch_finished = Signal(str)               # reason
    log            = Signal(str)               # 人类可读日志

    def __init__(self, parent=None):
        super().__init__(parent)

        self._plan: list = []
        self._options: dict = {}
        self._current: int = 0
        self._total: int = 0
        self._active: bool = False

        # ── 本轮收尾等待状态 ──
        self._waiting_round_end: bool = False

        # 间隔定时器（驱动下一轮）
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._next)

        # 收尾兜底定时器
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._on_settle_timeout)

    # ══════════════════════════════════════════════════════════════
    # 公开查询
    # ══════════════════════════════════════════════════════════════
    @property
    def active(self) -> bool:
        return self._active

    @property
    def current(self) -> int:
        return self._current

    @property
    def total(self) -> int:
        return self._total

    def get_params(self, index: int) -> dict:
        """获取第 index 次测试的参数（用于回灌目标压力等元信息）"""
        if 0 <= index < len(self._plan):
            return dict(self._plan[index])
        return {}

    # ══════════════════════════════════════════════════════════════
    # 启动 / 中止
    # ══════════════════════════════════════════════════════════════
    def start(self, plan: list, options: dict):
        """启动批量：plan 是扁平化的参数列表，每项对应一次单次测试"""
        if self._active:
            self.log.emit("⚠ 批量执行器正在运行")
            return

        if not plan:
            self.log.emit("⚠ 批量计划为空")
            self.batch_finished.emit("无任务")
            return

        self._plan    = list(plan)
        self._options = dict(options)
        self._current = 0
        self._total   = len(plan)
        self._active  = True
        self._waiting_round_end = False

        interval = self._options.get("interval", 3.0)
        stop_on_fail = self._options.get("stop_on_fail", False)
        self.log.emit("╔═ 批量测试开始 ═")
        self.log.emit(f"   共 {self._total} 次 · "
                      f"间隔 {interval}s · "
                      f"失败中止 {'开' if stop_on_fail else '关'}")

        self._next()

    def abort(self, reason: str = "用户中止"):
        """中止批量"""
        if not self._active:
            return
        self._timer.stop()
        self._settle_timer.stop()
        self._waiting_round_end = False
        self._finish(reason)

    # ══════════════════════════════════════════════════════════════
    # MainWindow 回调
    # ══════════════════════════════════════════════════════════════
    def on_test_finished(self, result: dict):
        """
        由 MainWindow 在单次测试完成后调用（首帧 0x02 到达时）。
        只记录结果、发信号，不立即启动下一轮。
        """
        if not self._active:
            return

        index = self._current
        self.test_finished.emit(index, result)
        self._current += 1

        # 失败中止：不必等曲线，直接收尾
        if self._options.get("stop_on_fail") and not result.get("qualified", True):
            self._finish("失败中止")
            return

        # 等本轮曲线自然结束
        self._waiting_round_end = True
        timeout_ms = self._options.get("settle_timeout_ms", SETTLE_TIMEOUT_MS)
        self._settle_timer.start(timeout_ms)
        self.log.emit(f"   等待本轮收尾（超时 {timeout_ms / 1000:.0f}s）…")

    def on_round_ended(self):
        """
        由 MainWindow 调用：本轮单次测试的曲线已自然结束。
        """
        if not self._active or not self._waiting_round_end:
            return

        self._waiting_round_end = False
        self._settle_timer.stop()

        if self._current >= self._total:
            self._finish("全部完成")
            return

        delay_ms = int(self._options.get("interval", 3.0) * 1000)
        self.log.emit(f"   等待 {delay_ms / 1000:.1f}s 后继续下一轮 …")
        self._timer.start(max(100, delay_ms))

    # ══════════════════════════════════════════════════════════════
    # 内部
    # ══════════════════════════════════════════════════════════════
    def _on_settle_timeout(self):
        """兜底：本轮收尾超时，强制进下一轮"""
        if not self._waiting_round_end:
            return
        self.log.emit("⚠ 本轮收尾超时，强制进入下一轮")
        self.on_round_ended()

    def _next(self):
        if not self._active:
            return
        if self._current >= self._total:
            self._finish("全部完成")
            return

        params = self._plan[self._current]
        # 标记批次索引，供 MainWindow 判断是否首轮
        params["_batch_index"] = self._current
        self.test_started.emit(self._current, self._total, params)
        self.test_requested.emit(dict(params))

    def _finish(self, reason: str):
        self._active = False
        self._timer.stop()
        self._settle_timer.stop()
        self._waiting_round_end = False
        self.log.emit(f"╚═ 批量测试结束（{reason}）═")
        self.batch_finished.emit(reason)