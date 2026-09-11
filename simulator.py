# -*- coding: utf-8 -*-
"""
simulator.py — 模拟设备（独立模块）

不依赖 Qt / 串口。按时间推进，产出协议帧 dict。

注意：充气段第一帧必须 > CHART_STOP_PRESSURE(0.1)
      否则 main_window 的"压力降到 0.1 停止绘图"逻辑会立即掐断曲线。
      真实设备首帧约 30 mmHg，这里用 k 下限模拟。
"""

import time
import math
import random

from config import PROTOCOL


# ── 时序参数（秒）───────────────────────────────
INFLATE_SEC   = 4.0
TEST_SEC      = 30.0
RELEASE_SEC   = 12.0
RELEASE_TAU   = 2.5

# ── 物理参数 ────────────────────────────────────
LEAK_RATE     = 0.018

# ── 采样 ────────────────────────────────────────
EMIT_INTERVAL = 0.2


class Simulator:

    def __init__(self):
        self._active     = False
        self._t0         = 0.0
        self._last_emit  = 0.0
        self._target     = 0.0
        self._duration   = 0.0

    @property
    def active(self) -> bool:
        return self._active

    def start(self, pressure: int, duration: int):
        self._target    = float(pressure)
        self._duration  = float(duration)
        self._t0        = time.time()
        self._last_emit = 0.0
        self._active    = True

    def stop(self):
        self._active    = False
        self._t0        = 0.0
        self._last_emit = 0.0
        self._target    = 0.0
        self._duration  = 0.0

    def step(self):
        if not self._active:
            return None

        now     = time.time()
        elapsed = now - self._t0

        inflate_end = INFLATE_SEC
        test_end    = inflate_end + self._duration + TEST_SEC
        release_end = test_end + RELEASE_SEC

        # 泄气结束：最后一帧 0.0，停
        if elapsed >= release_end:
            self._active = False
            return self._make_complete(pressure=0.0)

        if now - self._last_emit < EMIT_INTERVAL:
            return None
        self._last_emit = now

        # ④ 泄气段
        if elapsed >= test_end:
            t_rel = elapsed - test_end
            p = self._target * math.exp(-t_rel / RELEASE_TAU)
            p += random.uniform(-0.02, 0.02)
            return self._make_complete(pressure=p)

        # ① 充气段
        if elapsed < inflate_end:
            k = elapsed / inflate_end
            k = max(k, 0.05)          # ← 关键：起点不要 0
            p = self._target * (1.0 - (1.0 - k) ** 2)
            return self._make_running(pressure=p, total_time=0)

        # ② 稳压 / ③ 测试
        t_after = elapsed - inflate_end
        tt = int(t_after)

        if t_after < self._duration:
            p = self._target + random.uniform(-0.15, 0.15)
        else:
            t_test = t_after - self._duration
            p = self._target - LEAK_RATE * t_test
            p += random.uniform(-0.15, 0.15)

        return self._make_running(pressure=p, total_time=tt)

    def _make_running(self, pressure: float, total_time: int) -> dict:
        return {
            "status":          PROTOCOL["status_running"],
            "status_name":     PROTOCOL["status_names"][PROTOCOL["status_running"]],
            "pressure":        pressure,
            "stable_pressure": 0.0,
            "leak_rate":       0.0,
            "total_time":      total_time,
            "raw":             b"",
        }

    def _make_complete(self, pressure: float) -> dict:
        stable = self._target - LEAK_RATE * (self._duration + TEST_SEC)
        leak   = LEAK_RATE * 60.0
        return {
            "status":          PROTOCOL["status_complete"],
            "status_name":     PROTOCOL["status_names"][PROTOCOL["status_complete"]],
            "pressure":        pressure,
            "stable_pressure": round(stable, 2),
            "leak_rate":       round(leak, 2),
            "total_time":      int(INFLATE_SEC + self._duration + TEST_SEC),
            "raw":             b"",
        }