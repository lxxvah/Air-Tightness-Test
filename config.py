# -*- coding: utf-8 -*-
"""
config.py — 全局配置

本文件集中管理整个上位机的：
  1. 配色        COLORS
  2. 字体        FONT_STACK / MONO_STACK
  3. 上下位机协议  PROTOCOL
  4. 串口参数     SERIAL_DEFAULTS
  5. 单次测试默认值 TEST_DEFAULTS
  6. 输入框范围    TEST_RANGES
  7. 批量测试默认值 BATCH_DEFAULTS
  8. 模拟器参数    SIMULATION（注意：当前未生效，真参数在 simulator.py）
  9. 设备识别      DEVICE_IDENTIFICATION
  10. 运行时观察期  TEST_RUNTIME
  11. 全局样式      GLOBAL_QSS

═══════════════════════════════════════════════════════════════════
改动须知（重要！）
═══════════════════════════════════════════════════════════════════
  · COLORS / GLOBAL_QSS     → 全局视觉，改后所有界面跟着变
  · PROTOCOL                → 改前必须同步下位机固件，否则协议不匹配
  · TEST_DEFAULTS/RANGES    → 程序启动时输入框的初值 / 上下限
  · BATCH_DEFAULTS          → 批量窗口初始值
  · SERIAL_DEFAULTS         → 串口连接默认参数
  · DEVICE_IDENTIFICATION   → 自动识别 VID/PID，换芯片必须改
  · TEST_RUNTIME            → 影响进度条、超时判定，谨慎改
═══════════════════════════════════════════════════════════════════
"""


# ═══════════════════════════════════════════════════════════════════
# 一、COLORS — 全局配色
# ═══════════════════════════════════════════════════════════════════
# 所有界面颜色都从这取，改一处全局生效。
#
# 【如何改主色调】
#   把 primary / ink / ink_strong 这三个一起换成同一个色系即可，
#   例如把黑 (#080808) 换成蓝 (#146ef5)：
#       "primary":    "#146ef5"
#       "ink":        "#0a2540"
#       "ink_strong": "#0d47a1"
#
# 【语义色不要随便改】
#   blue_info / orange / green / red 代表状态（运行中/测试中/合格/不合格），
#   改了用户会误解。
# ═══════════════════════════════════════════════════════════════════
COLORS = {
    # ── 主色系 ──
    "primary":      "#080808",   # 主色：主按钮背景、进度条填充、曲线、选中态
                                 #   改动 → 主按钮、曲线、进度条一起变
    "on_primary":   "#ffffff",   # 主色上的文字色：主按钮文字、选中文字
                                 #   若 primary 变浅色，这里要变深色
    "ink":          "#080808",   # 主文字：标题、数值
                                 #   改动 → 所有标题和数字的颜色
    "ink_strong":   "#222222",   # 主按钮 hover 态背景
                                 #   改动 → 鼠标悬停主按钮时的颜色

    # ── 文字层级 ──
    "body":         "#363636",   # 正文：日志文字、复选框
    "body_mid":     "#5a5a5a",   # 中等文字：字段标签（"目标压力"、"稳压时间"）
    "mute":         "#898989",   # 淡色：eyebrow（PARAMETERS等）、单位、坐标轴
    "mute_soft":    "#ababab",   # 最淡：状态圆点空闲色、按钮 disabled

    # ── 分隔线 ──
    "hairline":     "#d8d8d8",   # 卡片边框、输入框边框、表格分隔线
    "canvas":       "#ffffff",   # 全局背景

    # ── 备用色（当前未使用，可自由支配）──
    "purple":       "#7a3dff",
    "pink":         "#ed52cb",
    "blue":         "#3b89ff",
    "yellow":       "#ffae13",

    # ── 语义色（谨慎修改）──
    "blue_info":    "#146ef5",   # "充气中/稳压中"状态圆点
    "orange":       "#ff6b00",   # "测试中"状态、批量"已停止"
    "green":        "#00d722",   # "合格"状态、"✅ N" 统计
    "red":          "#ee1d36",   # "不合格"状态、TARGET 虚线、"❌ N" 统计
}


# ═══════════════════════════════════════════════════════════════════
# 二、字体族
# ═══════════════════════════════════════════════════════════════════
# 这是"候选列表"，不是单个字体。系统里找不到第一个就往后找。
#
# 【如何换字体】
#   把想用的字体名放到最前面：
#       FONT_STACK = ('"微软雅黑", "Microsoft YaHei", sans-serif')
#
# 【为什么用候选列表】
#   跨平台兼容：Windows 有 Inter 就用 Inter，没有就 Segoe UI，
#   中文回退到 PingFang SC 或 Microsoft YaHei。
# ═══════════════════════════════════════════════════════════════════
FONT_STACK = ('"Inter", "WF Visual Sans", "Segoe UI", '
              '"PingFang SC", "Microsoft YaHei", sans-serif')
MONO_STACK = ('"Inconsolata", "JetBrains Mono", "Consolas", '
              '"SF Mono", monospace')


# ═══════════════════════════════════════════════════════════════════
# 三、PROTOCOL — 上下位机协议
# ═══════════════════════════════════════════════════════════════════
# ⚠️ 改这里之前必须同步下位机固件，否则协议对不上，通信失败。
#
# 【协议总览】
#   上位机 → 下位机：
#     复位命令   01 00 00 00 00 00 00 00
#     断开命令   00 00 00 00 00 00 00 00
#     测试命令   04 13 cuff pH pL dur    （6 字节）
#
#   下位机 → 上位机（11 字节，从 0xAA 起）：
#     [0]     AA          帧头
#     [1..2]  当前压力+10 ×100 大端  → mmHg = raw/100 - 10
#     [3]     状态：0等待 1运行 2完成 3失败
#     [4..5]  总测量时间（秒）大端
#     [6..7]  稳定压力×100 大端  → mmHg = raw/100
#     [8..9]  漏气率×100  大端  → mmHg/min = raw/100
#     [10]    保留
# ═══════════════════════════════════════════════════════════════════
PROTOCOL = {
    # ── 上位机 → 下位机命令 ──
    "cmd_enter_pc": bytes([0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
        # 用途：进入 PC 模式（现在是复位序列的第 2 步）
        # 改动：下位机改了复位命令才改
    "cmd_exit_pc":  bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
        # 用途：退出 PC（断开连接），批量中间轮的断开命令
        # 改动：同上

    "cmd_function_id":   0x04,   # 测试命令功能码
    "sub_function":      0x13,   # 测试命令子功能码
    "cuff_type_ext":     0x00,   # 袖带类型：外部袖带
    "cuff_type_int":     0x01,   # 袖带类型：内部袖带
    "cmd_frame_length":  6,      # 测试命令字节数（04 13 cuff pH pL dur）

    # ── 下位机 → 上位机响应帧 ──
    "resp_frame_length":   11,   # 一帧固定 11 字节
    "resp_header":         0xAA, # 帧头字节（找帧起点用）

    # 当前压力字段：raw 是 2 字节大端
    "pressure_offset":     1,        # 从帧头后第 1 字节开始
    "pressure_bytes":      2,        # 占 2 字节
    "pressure_scale":      100.0,    # 换算：raw / scale
    "pressure_bias":       10.0,     # 再减去 bias

    # 状态字段：1 字节
    "status_offset":       3,
    "status_waiting":      0x00,     # 状态码 0 = 等待
    "status_running":      0x01,     # 状态码 1 = 运行中
    "status_complete":     0x02,     # 状态码 2 = 完成（收到即结算）
    "status_failed":       0x03,     # 状态码 3 = 失败（收到即中止）
    "status_names": {                # 日志里显示的中文名
        0x00: "等待",
        0x01: "运行",
        0x02: "完成",
        0x03: "失败",
    },

    # 总测量时间字段：2 字节大端（秒）
    "total_time_offset":   4,
    "total_time_bytes":    2,

    # 稳定压力字段：2 字节大端
    "stable_pressure_offset": 6,
    "stable_pressure_bytes":  2,
    "stable_pressure_scale":  100.0,   # raw / scale

    # 漏气率字段：2 字节大端
    "leak_rate_offset":    8,
    "leak_rate_bytes":     2,
    "leak_rate_scale":     100.0,      # raw / scale
}


# ═══════════════════════════════════════════════════════════════════
# 四、SERIAL_DEFAULTS — 串口默认参数
# ═══════════════════════════════════════════════════════════════════
SERIAL_DEFAULTS = {
    "port":     "COM19",
        # 用途：串口对话框默认选中、无串口时的占位
        # 改动：改成本机实际串口号即可，如 "COM3"

    "baudrate": 115200,
        # 用途：自动连接 / 手动连接时的默认波特率
        # 改动：下位机不是 115200 就必须改（常见 9600 / 57600）

    "timeout":  1.0,
        # 用途：serial.Serial 的 timeout（读串口阻塞秒数）
        # 改动：一般不调。调小会让读操作立即返回，调大会阻塞线程

    "poll_ms":  30,
        # 用途：worker 线程的轮询周期（毫秒）
        # 改动：
        #   调小（如 20）→ 刷新更密，界面响应更快，CPU 略高
        #   调大（如 100）→ 界面帧率降到 10fps，肉眼感觉卡顿
}


# ═══════════════════════════════════════════════════════════════════
# 五、TEST_DEFAULTS — 单次测试参数默认值
# ═══════════════════════════════════════════════════════════════════
# 程序启动时主窗口输入框显示的初值。
# 批量窗口"初始那一行"也读这里（前提是用户没在主窗口改过）。
TEST_DEFAULTS = {
    "pressure":   300,
        # 目标压力默认值（mmHg）。出现在："目标压力"输入框初值
        # 改动：改成 500 → 程序启动就显示 500

    "duration":   30,
        # 稳压时间默认值（秒）。出现在："稳压时间"输入框初值
        # 改动：改成 60 → 默认稳压 60 秒

    "threshold":  6.00,
        # 合格阈值默认值（mmHg/min）。出现在："合格阈值"输入框初值
        # 改动：改成 3.00 → 更严格

    "cuff_type":  PROTOCOL["cuff_type_ext"],
        # 袖带类型默认值（外部/内部）
        # 改动：换成 PROTOCOL["cuff_type_int"] → 默认内部袖带
}


# ═══════════════════════════════════════════════════════════════════
# 六、TEST_RANGES — 输入框上下限
# ═══════════════════════════════════════════════════════════════════
# 每个 QSpinBox / QDoubleSpinBox 的 setRange 参数。
# 【注意】这是"允许输入的范围"，不是"推荐值"。
# 改了上限，用户能输入更大值，但设备未必支持。
TEST_RANGES = {
    "pressure":   (0, 400),
        # 目标压力范围：0 ~ 400 mmHg

    "duration":   (1, 300),
        # 稳压时间范围：1 ~ 300 秒

    "threshold":  (0.01, 20.0),
        # 合格阈值范围：0.01 ~ 20.0 mmHg/min
}


# ═══════════════════════════════════════════════════════════════════
# 七、BATCH_DEFAULTS — 批量测试默认值
# ═══════════════════════════════════════════════════════════════════
BATCH_DEFAULTS = {
    "count":         1,
        # 批量窗口"初始行"的次数默认值
        # 改动：改成 10 → 打开批量窗口默认 10 次

    "interval":      3.0,
        # 两轮之间的间隔（秒）
        # 【语义】上一轮曲线停止 + 复位完成后，再等 interval 秒
        # 改动：
        #   0    → 上一轮刚停就马上下一轮
        #   5    → 多等 5 秒，给设备降温/稳定

    "stop_on_fail":  False,
        # "失败时中止"复选框默认状态
        # 改动：True → 默认勾选，任何一轮不合格就停整批
}


# ═══════════════════════════════════════════════════════════════════
# 八、SIMULATION — 模拟器参数
# ═══════════════════════════════════════════════════════════════════
# ⚠️ 注意：这两个键目前在代码里"没有被读取"。
# 实际生效的模拟参数在 simulator.py 顶部常量：
#   INFLATE_SEC = 4.0
#   LEAK_RATE   = 0.018
#
# 如果想让它生效，需要改 simulator.py 从这读。
SIMULATION = {
    "inflate_sec":  4.0,     # 充气时长（秒）
    "leak_coeff":   0.018,   # 泄漏系数
}


# ═══════════════════════════════════════════════════════════════════
# 九、DEVICE_IDENTIFICATION — 设备自动识别
# ═══════════════════════════════════════════════════════════════════
# 自动识别时按 USB VID/PID 匹配串口。
# 0x1A86 / 0x7523 是 CH340 芯片的常见组合。
DEVICE_IDENTIFICATION = {
    "SIMULATOR_VID":        0x1A86,
        # 设备厂商 ID
        # 改：换成下位机实际的 VID（如 CP2102 是 0x10C4）

    "SIMULATOR_PID":        0x7523,
        # 设备产品 ID
        # 改：换成下位机实际的 PID（CP2102 是 0xEA60）

    "DISCONNECT_DELAY":     0.2,
        # 关闭串口前的 sleep（秒）
        # 用途：某些设备在端口还开着时不响应断开命令

    "SERIAL_IDLE_INTERVAL": 0.001,
        # worker 线程空闲轮询下限（秒）
        # 用途：没数据时线程 sleep 这个值再检查
        # 改：调大降 CPU，调小升响应

    "FALLBACK_SCAN_ALL":    True,
        # VID/PID 不匹配时，是否回退到"扫全部串口"
        # 改：
        #   True  → 找不到匹配设备时，随便连一个（方便调试）
        #   False → 严格只连 VID/PID 匹配的（生产环境）
}


# ═══════════════════════════════════════════════════════════════════
# 十、TEST_RUNTIME — 单次测试运行时参数
# ═══════════════════════════════════════════════════════════════════
TEST_RUNTIME = {
    "observation_sec": 300,
        # "观察期"时长（秒）
        # 【影响】
        #   1) _total_expected = duration + observation_sec
        #   2) 进度条分母
        #   3) _deadline = t0 + duration + observation + margin
        # 改：300 → 60 会让进度条跑得更快，测试显得更短

    "timeout_margin":  90.0,
        # 超时兜底（秒）
        # 【语义】超过 duration + observation + margin 还没收到 0x02，
        #         判定为"设备未在规定时间内完成流程"，走 _abort
        # 改：调小（如 30）设备偶尔慢一帧就误判超时

    "log_flush_ms": 2000,
        # 日志缓冲 flush 间隔（毫秒）
        # 【语义】_log() 只把日志行追加到内存缓冲，
        #         每 log_flush_ms 毫秒定时批量写入磁盘一次。
        #         测试结束后会做最后一次 flush，正常流程零丢失。
        # 【影响】
        #   1) 主线程阻塞频率（数值越大阻塞越少）
        #   2) 崩溃/断电时最多丢失 log_flush_ms 毫秒的日志
        # 【推荐值】
        #   1000 → 崩溃最多丢 1 秒（约 10 行）
        #   2000 → 崩溃最多丢 2 秒（约 20 行）—— 默认，主线程更省
        #   3000 → 崩溃最多丢 3 秒（约 30 行）
        # 改：调小更保险，调大更省 CPU；不建议超过 5000
}


# ═══════════════════════════════════════════════════════════════════
# 十一、GLOBAL_QSS — 全局样式表
# ═══════════════════════════════════════════════════════════════════
# 整块 QSS 字符串，控制所有控件基础外观。
# 【改动须知】改这一块会同时影响主窗口、串口对话框、批量窗口、弹窗。
#
# 关键字段速查：
#   QWidget → font-size: 14px   全局字号
#   QFrame#Card → border-radius 卡片圆角
#   QPushButton#ButtonPrimary → padding  主按钮内边距
#   QLineEdit/QSpinBox → padding: 8px 12px  输入框高度
#   QPlainTextEdit#LogView → font-size: 12px  日志字号
#   QProgressBar → height: 6px  进度条粗细
#   QScrollBar:vertical → width: 8px  滚动条宽度
# ═══════════════════════════════════════════════════════════════════
GLOBAL_QSS = f"""
/* ── 全局基础 ── */
QWidget {{
    background-color: {COLORS['canvas']};
    color: {COLORS['ink']};
    font-family: {FONT_STACK};
    font-size: 14px;
}}
/* 改 font-size: 14px → 16px 会让所有文字变大 */

/* ── 菜单栏 ── */
QMenuBar {{
    background-color: {COLORS['canvas']};
    border-bottom: 1px solid {COLORS['hairline']};
    padding: 6px 12px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 12px;      /* 改这里控制菜单项点击热区 */
    border-radius: 4px;
    color: {COLORS['ink']};
    font-weight: 500;
}}
QMenuBar::item:selected {{ background-color: #f2f2f2; }}   /* 悬停色 */
QMenuBar::item:pressed  {{ background-color: #e6e6e6; }}   /* 按下色 */

/* ── 下拉菜单 ── */
QMenu {{
    background-color: {COLORS['canvas']};
    border: 1px solid {COLORS['hairline']};
    border-radius: 6px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 20px;      /* 菜单项内边距 */
    border-radius: 4px;
    color: {COLORS['ink']};
}}
QMenu::item:selected {{
    background-color: {COLORS['primary']};
    color: {COLORS['on_primary']};
}}
QMenu::separator {{
    height: 1px;
    background: {COLORS['hairline']};
    margin: 6px 10px;
}}

/* ── 卡片 ── */
QFrame#Card {{
    background-color: {COLORS['canvas']};
    border: 1px solid {COLORS['hairline']};
    border-radius: 8px;     /* 改这里控制卡片圆角大小 */
}}

/* ── 主按钮（黑底白字）── */
QPushButton#ButtonPrimary {{
    background-color: {COLORS['primary']};
    color: {COLORS['on_primary']};
    border: none;
    border-radius: 4px;
    padding: 12px 20px;     /* 改这里控制按钮高度 */
    font-size: 16px;
    font-weight: 500;
}}
QPushButton#ButtonPrimary:hover    {{ background-color: {COLORS['ink_strong']}; }}
QPushButton#ButtonPrimary:pressed  {{ background-color: #000000; }}
QPushButton#ButtonPrimary:disabled {{ background-color: {COLORS['mute_soft']}; color: #f5f5f5; }}

/* ── 次要按钮（白底黑框）── */
QPushButton#ButtonSecondary {{
    background-color: {COLORS['canvas']};
    color: {COLORS['ink']};
    border: 1px solid {COLORS['hairline']};
    border-radius: 4px;
    padding: 12px 20px;
    font-size: 16px;
    font-weight: 500;
}}
QPushButton#ButtonSecondary:hover    {{ border-color: {COLORS['ink']}; }}
QPushButton#ButtonSecondary:pressed  {{ background-color: #f5f5f5; }}
QPushButton#ButtonSecondary:disabled {{ color: {COLORS['mute_soft']}; border-color: #ebebeb; }}

/* ── 输入框（QLineEdit / 数字框 / 下拉框）── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COLORS['canvas']};
    color: {COLORS['ink']};
    border: 1px solid {COLORS['hairline']};
    border-radius: 4px;
    padding: 8px 12px;      /* 改这里控制输入框高度 */
    font-size: 14px;
    selection-background-color: {COLORS['primary']};
    selection-color: {COLORS['on_primary']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLORS['ink']};   /* 聚焦时边框变黑 */
}}
/* 隐藏数字框的上下箭头 */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; height: 0px; border: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}   /* 下拉箭头区域 */

/* ── 日志窗口 ── */
QPlainTextEdit#LogView {{
    background-color: {COLORS['canvas']};
    color: {COLORS['body']};
    border: 1px solid {COLORS['hairline']};
    border-radius: 6px;
    padding: 10px 12px;
    font-family: {MONO_STACK};   /* 等宽字体 */
    font-size: 12px;             /* 日志字号，改小可显示更多行 */
    selection-background-color: {COLORS['primary']};
    selection-color: {COLORS['on_primary']};
}}

/* ── 进度条 ── */
QProgressBar {{
    background-color: #f0f0f0;
    border: none;
    border-radius: 3px;
    height: 6px;                /* 改这里控制进度条粗细 */
}}
QProgressBar::chunk {{
    background-color: {COLORS['primary']};
    border-radius: 3px;
}}

/* ── 垂直滚动条 ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;                 /* 改这里控制滚动条宽度 */
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['hairline']};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {COLORS['mute_soft']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ── 特殊用途 Label ── */
QLabel#Eyebrow      {{ color: {COLORS['mute']}; }}   /* "PARAMETERS" 等小字 */
QLabel#SectionTitle {{ color: {COLORS['ink']};  }}   /* "参数设置" 等标题 */
QLabel#Caption      {{ color: {COLORS['mute']}; font-size: 12px; }}
"""