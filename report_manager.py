# -*- coding: utf-8 -*-
"""
report_manager.py — 日志 / 测试结果的集中管理

职责：
  · 自动在程序目录下建 Test_Results/ 和 Test_Logs/
  · 按固定命名规则写入单次/批量测试的结果 CSV 和日志 LOG
  · 打开结果 / 日志文件夹

命名规则：
  单次测试结果：单次测试_{压力}xmmHg_{时长}s_{时间戳}.csv
  单次测试日志：单次_{压力}xmmHg_{时长}s_{时间戳}.log
  批量测试结果：批量测试_{时间戳}.csv
  批量测试日志：批量_{时间戳}.log

时间戳：{年}年{月}月{日}日{时}时{分}分{秒}秒
  例：2026年9月11日09时26分40秒

编码：
  CSV → utf-8-sig（Excel 打开无乱码）
  LOG → utf-8
"""

import csv
import os
import subprocess
import sys
from datetime import datetime


DIR_RESULTS = "Test_Results"
DIR_LOGS    = "Test_Logs"


# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════
def _app_dir() -> str:
    """程序所在目录（打包后为 exe 所在目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    if sys.argv and sys.argv[0] and os.path.isfile(sys.argv[0]):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_dirs():
    base = _app_dir()
    r = os.path.join(base, DIR_RESULTS)
    l = os.path.join(base, DIR_LOGS)
    os.makedirs(r, exist_ok=True)
    os.makedirs(l, exist_ok=True)
    return r, l


# ═══════════════════════════════════════════════════════════════
# 时间戳
# ═══════════════════════════════════════════════════════════════
def format_timestamp(dt: datetime) -> str:
    """2026年9月11日09时26分40秒"""
    return (f"{dt.year}年{dt.month}月{dt.day}日"
            f"{dt.hour:02d}时{dt.minute:02d}分{dt.second:02d}秒")


# ═══════════════════════════════════════════════════════════════
# 单次测试
# ═══════════════════════════════════════════════════════════════
def save_single_result(dt_start, pressure, duration, threshold, cuff_name,
                       stable_pressure, leak_rate, total_time, qualified) -> str:
    r, _ = _ensure_dirs()
    fn = f"单次测试_{pressure}xmmHg_{duration}s_{format_timestamp(dt_start)}.csv"
    path = os.path.join(r, fn)

    tag = "✅ 合格" if qualified else "❌ 不合格"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["参数设置"])
        w.writerow(["目标压力 (mmHg)", "稳压时间 (s)",
                    "合格阈值 (mmHg/min)", "袖带类型"])
        w.writerow([pressure, duration, f"{threshold:.2f}", cuff_name])
        w.writerow([])
        w.writerow(["测试结果"])
        w.writerow(["稳定压力 (mmHg)", "漏气率 (mmHg/min)",
                    "总测量时间 (s)", "判定"])
        w.writerow([f"{stable_pressure:.2f}", f"{leak_rate:.2f}",
                    total_time, tag])
        w.writerow([])
        w.writerow(["判定"])
        w.writerow(["阈值 (mmHg/min)", f"{threshold:.2f}"])
        w.writerow(["结论", tag])
    return path


def save_single_log(dt_start, pressure, duration, log_text) -> str:
    _, l = _ensure_dirs()
    fn = f"单次_{pressure}xmmHg_{duration}s_{format_timestamp(dt_start)}.log"
    path = os.path.join(l, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_text)
    return path


# ═══════════════════════════════════════════════════════════════
# 批量测试
# ═══════════════════════════════════════════════════════════════
def save_batch_result(dt_start, plan_rows, result_rows) -> str:
    """
    plan_rows:   [(压力, 时长, 阈值, 次数), ...]
    result_rows: [(#, 时间, 目标压力, 稳定压, 漏气率, 判定), ...]
    """
    r, _ = _ensure_dirs()
    fn = f"批量测试_{format_timestamp(dt_start)}.csv"
    path = os.path.join(r, fn)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["压力档设置"])
        w.writerow(["目标压力 (mmHg)", "稳压时间 (s)",
                    "合格阈值 (mmHg/min)", "次数"])
        for row in plan_rows:
            w.writerow(row)

        w.writerow([])
        w.writerow(["测试结果"])
        w.writerow(["#", "时间", "目标压力 (mmHg)",
                    "稳定压 (mmHg)", "漏气率 (mmHg/min)", "判定"])
        for row in result_rows:
            w.writerow(row)

        w.writerow([])
        n_all = len(result_rows)
        n_ok = sum(1 for r_ in result_rows if len(r_) > 5 and r_[5] == "✅ 合格")
        w.writerow(["汇总"])
        w.writerow(["总次数", n_all])
        w.writerow(["合格", n_ok])
        w.writerow(["不合格", n_all - n_ok])
    return path


def save_batch_log(dt_start, log_text) -> str:
    _, l = _ensure_dirs()
    fn = f"批量_{format_timestamp(dt_start)}.log"
    path = os.path.join(l, fn)
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_text)
    return path


# ═══════════════════════════════════════════════════════════════
# 打开文件夹
# ═══════════════════════════════════════════════════════════════
def open_results_folder():
    r, _ = _ensure_dirs()
    _open_path(r)


def open_logs_folder():
    _, l = _ensure_dirs()
    _open_path(l)


def _open_path(path: str):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass