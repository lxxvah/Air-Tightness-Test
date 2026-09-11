# -*- coding: utf-8 -*-
"""serial_worker.py — 串口数据发送 / 接收处理（模拟逻辑已抽到 simulator.py）"""

import time
import queue

from PySide6.QtCore import QThread, Signal

from config import (
    PROTOCOL,
    SERIAL_DEFAULTS,
    DEVICE_IDENTIFICATION as DEVID,
)
from simulator import Simulator

try:
    import serial
    import serial.tools.list_ports as list_ports
    HAS_PYSERIAL = True
except ImportError:
    serial = None
    list_ports = None
    HAS_PYSERIAL = False


# ═══════════════════════════════════════════════════════════════════
# 协议编解码
# ═══════════════════════════════════════════════════════════════════

def build_leak_test_command(pressure: int,
                            duration: int,
                            cuff_type: int = PROTOCOL["cuff_type_ext"]) -> bytes:
    ph = (pressure >> 8) & 0xFF
    pl = pressure & 0xFF
    return bytes([
        PROTOCOL["cmd_function_id"],
        PROTOCOL["sub_function"],
        cuff_type,
        ph,
        pl,
        duration & 0xFF,
    ])


def build_reset() -> bytes:
    return PROTOCOL["cmd_enter_pc"]


def build_disconnect() -> bytes:
    return PROTOCOL["cmd_exit_pc"]


build_enter_pc = build_reset
build_exit_pc  = build_disconnect


def _read_be(data: bytes, offset: int, n: int) -> int:
    v = 0
    for i in range(n):
        v = (v << 8) | data[offset + i]
    return v


def parse_response_frame(data: bytes) -> dict | None:
    if len(data) != PROTOCOL["resp_frame_length"]:
        return None
    if data[0] != PROTOCOL["resp_header"]:
        return None

    p_raw = _read_be(data, PROTOCOL["pressure_offset"], PROTOCOL["pressure_bytes"])
    pressure = p_raw / PROTOCOL["pressure_scale"] - PROTOCOL["pressure_bias"]

    status = data[PROTOCOL["status_offset"]]

    total_time = _read_be(data, PROTOCOL["total_time_offset"],
                          PROTOCOL["total_time_bytes"])

    sp_raw = _read_be(data, PROTOCOL["stable_pressure_offset"],
                      PROTOCOL["stable_pressure_bytes"])
    stable_pressure = sp_raw / PROTOCOL["stable_pressure_scale"]

    lr_raw = _read_be(data, PROTOCOL["leak_rate_offset"],
                      PROTOCOL["leak_rate_bytes"])
    leak_rate = lr_raw / PROTOCOL["leak_rate_scale"]

    return {
        "status":          status,
        "status_name":     PROTOCOL["status_names"].get(status, f"0x{status:02X}"),
        "pressure":        pressure,
        "stable_pressure": stable_pressure,
        "leak_rate":       leak_rate,
        "total_time":      total_time,
        "raw":             data,
    }


# ═══════════════════════════════════════════════════════════════════
# 设备查询
# ═══════════════════════════════════════════════════════════════════

def find_device_ports() -> list:
    if not HAS_PYSERIAL or list_ports is None:
        return []
    vid = DEVID["SIMULATOR_VID"]
    pid = DEVID["SIMULATOR_PID"]
    return [p.device for p in list_ports.comports()
            if p.vid == vid and p.pid == pid]


def list_all_ports() -> list:
    if not HAS_PYSERIAL or list_ports is None:
        return []
    return [p.device for p in list_ports.comports()]


# ═══════════════════════════════════════════════════════════════════
# 工作线程
# ═══════════════════════════════════════════════════════════════════

class SerialWorker(QThread):
    connection_changed = Signal(bool, str)
    frame_received     = Signal(dict)
    error_occurred     = Signal(str)
    raw_tx             = Signal(bytes)
    raw_rx             = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q          = queue.Queue()
        self._running    = False
        self._serial     = None
        self._simulation = False
        self._sim        = Simulator()
        self._rx_buf     = bytearray()          # ← 新增

    def send(self, data: bytes):
        self._q.put(("send", data))

    def connect_port(self, port=None, baudrate=None, timeout=None):
        port     = port     or SERIAL_DEFAULTS["port"]
        baudrate = baudrate or SERIAL_DEFAULTS["baudrate"]
        timeout  = timeout  or SERIAL_DEFAULTS["timeout"]
        self._q.put(("connect", (port, baudrate, timeout)))

    def disconnect_port(self):
        self._q.put(("disconnect", None))

    def start_simulation(self, pressure: int, duration: int):
        self._q.put(("sim_start", (pressure, duration)))

    def stop_simulation(self):
        self._q.put(("sim_stop", None))

    def shutdown(self):
        self._running = False

    def run(self):
        self._running = True
        poll_ms = SERIAL_DEFAULTS["poll_ms"]
        idle_us = int(DEVID["SERIAL_IDLE_INTERVAL"] * 1_000_000)
        sleep_us = max(idle_us, int(poll_ms * 1000))
        while self._running:
            self._drain_queue()
            self._poll_source()
            self.usleep(sleep_us)
        self._close_serial()

    def _drain_queue(self):
        while True:
            try:
                cmd, arg = self._q.get_nowait()
            except queue.Empty:
                break
            if cmd == "send":
                self._do_send(arg)
            elif cmd == "connect":
                self._do_connect(*arg)
            elif cmd == "disconnect":
                self._close_serial()
                self._simulation = False
                self._sim.stop()
                self.connection_changed.emit(False, "已断开")
            elif cmd == "sim_start":
                self._start_sim(*arg)
            elif cmd == "sim_stop":
                self._simulation = False
                self._sim.stop()

    def _do_send(self, data: bytes):
        if self._simulation:
            self.raw_tx.emit(data)
            return
        if self._serial and self._serial.is_open:
            try:
                self._serial.write(data)
                self._serial.flush()
                self.raw_tx.emit(data)
            except Exception as e:
                self.error_occurred.emit(f"发送失败：{e}")
        else:
            self.error_occurred.emit("串口未打开，发送被忽略")

    def _do_connect(self, port, baudrate, timeout):
        if not HAS_PYSERIAL:
            self.connection_changed.emit(False, "未安装 pyserial")
            return
        self._close_serial()
        try:
            self._serial = serial.Serial(port, baudrate, timeout=timeout)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._simulation = False
            self._rx_buf.clear()                # ← 新增
            self.connection_changed.emit(True, f"已连接 {port} @ {baudrate}")
        except Exception as e:
            self._serial = None
            self.connection_changed.emit(False, f"连接失败：{e}")

    def _close_serial(self):
        if self._serial:
            try:
                time.sleep(DEVID["DISCONNECT_DELAY"])
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._rx_buf.clear()                    # ← 新增

    # ── 接收（累积缓冲 + 定长切帧）───────────────
    def _poll_source(self):
        if self._simulation:
            self._sim_step()
            return
        if not (self._serial and self._serial.is_open):
            return

        try:
            # 有多少读多少。read(n) 保证立即返回，不阻塞
            n = self._serial.in_waiting
            if n < 1:
                return

            self._rx_buf += self._serial.read(n)

            # 从缓冲里切出所有完整帧
            while len(self._rx_buf) >= PROTOCOL["resp_frame_length"]:
                if self._rx_buf[0] != PROTOCOL["resp_header"]:
                    # 当前字节不是帧头，找下一个 AA
                    i = self._rx_buf.find(PROTOCOL["resp_header"])
                    if i < 0:
                        self._rx_buf.clear()
                        return
                    del self._rx_buf[:i]
                    continue

                frame_bytes = bytes(self._rx_buf[:PROTOCOL["resp_frame_length"]])
                del self._rx_buf[:PROTOCOL["resp_frame_length"]]

                self.raw_rx.emit(frame_bytes)
                frame = parse_response_frame(frame_bytes)
                if frame:
                    self.frame_received.emit(frame)
        except Exception as e:
            self.error_occurred.emit(f"读取失败：{e}")
            self._close_serial()

    # ── 模拟（只做调度，逻辑在 Simulator 里）─────
    def _start_sim(self, pressure: int, duration: int):
        self._close_serial()
        self._sim.start(pressure, duration)
        self._simulation = True
        self.connection_changed.emit(True, "模拟模式")

    def _sim_step(self):
        frame = self._sim.step()
        if frame is None:
            return
        self.frame_received.emit(frame)
        if not self._sim.active:
            self._simulation = False