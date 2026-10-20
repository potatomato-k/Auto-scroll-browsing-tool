
import uiautomator2 as u2
from cnocr import CnOcr
import time
import random
import os
import sys
import math
from PIL import Image

# ==========================================
# 阶段 1：初始化与全局配置
# ==========================================
# 目标 App 包名(必填)：在下面引号中填入你要自动化的 App 的包名。
# 查询方法: adb shell pm list packages
# 例如: com.taobao.taobao
TARGET_APP_PACKAGE = "" # 例如 com.taobao.taobao
if not TARGET_APP_PACKAGE:
    print("❌ 未配置目标 App 包名：请将脚本顶部的 TARGET_APP_PACKAGE 填入你的 App 包名后重新运行。")
    exit()

# 浏览任务关键词：同时匹配"浏览15秒"和"浏览5秒"两类任务
# (注意："浏览5秒"不是"浏览15秒"的子串，两者互不误判)
TASK_KEYWORDS = ["浏览15秒", "浏览5秒"]

def is_browse_task_text(text):
    """判断一段 OCR 文字是否属于浏览类任务（15秒或5秒）"""
    return any(keyword in text for keyword in TASK_KEYWORDS)

# 搜索类页面(页面3)特征文字：覆盖"搜索有福利"页与"搜一搜"任务的搜索页
PAGE3_KEYWORDS = ["搜索有福利", "搜索发现", "历史搜索"]

def is_page3_text(text):
    """判断一段文字是否是搜索类页面(页面3)的特征"""
    return any(keyword in text for keyword in PAGE3_KEYWORDS)

def is_task_done_text(text):
    """判断是否为任务完成提示(兼容'任务已完成'与'任务完成'两种写法)"""
    return "任务已完成" in text or "任务完成" in text

print("正在加载 AI 视觉模型...")
ocr = CnOcr()

print("正在连接手机...")
try:
    d = u2.connect()
    screen_width, screen_height = d.window_size()
    print(f"成功连接设备。屏幕尺寸: {screen_width}x{screen_height}")
except Exception as e:
    print(f"手机连接失败: {e}")
    exit()

# ==========================================
# 日志系统：控制台输出全程留档 + OCR 识别结果逐条记录
# ==========================================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_browers.log")

# 固定文件名，每次运行自动覆盖上一次的日志；时间戳记录在文件内部
try:
    open(LOG_FILE, "w", encoding="utf-8").close()
except Exception:
    pass

def log(msg):
    """仅写入日志文件(带时间戳)，不输出到控制台，避免 OCR 结果刷屏"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

class _TeeStream:
    """把控制台输出逐行加时间戳后同步写入日志文件，无需改动任何 print"""
    def __init__(self, original):
        self._original = original
        self._file = open(LOG_FILE, "a", encoding="utf-8")
        self._buffer = ""
    def write(self, text):
        self._original.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._file.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
    def flush(self):
        self._original.flush()
        if self._buffer:
            self._file.write(f"[{time.strftime('%H:%M:%S')}] {self._buffer}\n")
            self._buffer = ""
        self._file.flush()
    def __getattr__(self, name):
        return getattr(self._original, name)

sys.stdout = _TeeStream(sys.stdout)
sys.stderr = _TeeStream(sys.stderr)
print(f"📝 本次运行日志(自动覆盖上次): {LOG_FILE}")
log(f"===== 运行开始 {time.strftime('%Y-%m-%d %H:%M:%S')} =====")

# 随机种子：每次运行随机生成并打印；需要复现本次行为时可 random.seed(同值)
RANDOM_SEED = random.randrange(10 ** 8)
random.seed(RANDOM_SEED)
print(f"🎲 本次随机种子: {RANDOM_SEED}")
log(f"随机种子: {RANDOM_SEED}")

# ==========================================
# 阶段 2：视觉与动作核心函数
# ==========================================

def get_screen_vision(region=None):
    """截屏并返回 OCR 识别结果。
    region: (left, top, right, bottom) 像素区域，只识别该区域以加速 OCR
            (识别耗时大致与像素面积成正比)；返回的坐标已换算回全屏坐标系。
            默认 None 为全屏识别。"""
    screenshot_path = "temp_screen.png"
    d.screenshot(screenshot_path)
    offset_x, offset_y = 0, 0
    if region is not None:
        img = Image.open(screenshot_path)
        img.crop(region).save(screenshot_path)
        offset_x, offset_y = region[0], region[1]
    result = ocr.ocr(screenshot_path)

    # 提取并整理识别结果为更好用的格式
    vision_data = []
    for item in result:
        text = item['text']
        # 取左上角的 X 和 Y 坐标，加上裁剪区域左上角的偏移量
        x = float(item['position'][0][0]) + offset_x
        y = float(item['position'][0][1]) + offset_y
        vision_data.append({"text": text, "x": x, "y": y})

    # 全部识别结果写入日志文件，便于排查"为什么没识别到"类问题
    log(f"OCR识别 {len(vision_data)} 项 (区域: {'全屏' if region is None else region}):")
    for it in vision_data:
        log(f"    y={it['y']:7.1f} x={it['x']:7.1f} | {it['text']}")

    return vision_data

def u2_region_exists(keyword, y_min, y_max):
    """快速路径：检查屏幕纵向区域(比例)内是否存在包含关键词的无障碍文本节点。
    仅原生页面有效；H5 页面查不到节点会返回 False，调用方需回退到 OCR。
    单次查询约 0.1~0.3 秒，远快于截图+OCR。"""
    try:
        for el in d(textContains=keyword):
            bounds = el.info.get('bounds') or {}
            top = bounds.get('top', -1)
            if screen_height * y_min <= top < screen_height * y_max:
                return True
    except Exception:
        pass
    return False

def human_swipe():
    """拟人化滑动"""
    start_x = screen_width // 2 + random.randint(-40, 40)
    start_y = int(screen_height * 0.8) + random.randint(-40, 40)
    end_x = screen_width // 2 + random.randint(-40, 40)
    end_y = int(screen_height * 0.3) + random.randint(-40, 40)
    duration = random.uniform(0.3, 0.7)
    d.swipe(start_x, start_y, end_x, end_y, duration)


def advanced_human_swipe(device):
    """
    拟人化滑动：贝塞尔曲线轨迹 + 缓动变速 + 低频平滑漂移。
    不再对每个轨迹点叠加独立随机噪声(高频抖动反而像机器)，改为：
    1. 整条轨迹叠加一条缓慢的横向正弦漂移(低频、平滑，像手指自然摆动)；
    2. 仅约 20% 的点出现 1 像素级微颤；
    3. 25% 概率改为快速轻拂，松手后页面带惯性继续滚动(真人常见滑动方式)。
    """
    width, height = device.window_size()

    # 分支一：快速轻拂(短耗时滑动，系统会按松手速度赋予惯性滚动)
    if random.random() < 0.25:
        start_x = width // 2 + random.randint(-30, 30)
        start_y = int(height * 0.75) + random.randint(-20, 20)
        end_x = width // 2 + random.randint(-20, 20)
        end_y = int(height * 0.45) + random.randint(-20, 20)
        duration = random.uniform(0.15, 0.25)
        print("  [拟人滑动] 快速轻拂(带惯性滚动)...")
        device.swipe(start_x, start_y, end_x, end_y, duration)
        return

    # 分支二：贝塞尔曲线慢滑
    # 1. 确定起点 (P0) 和终点 (P2)
    start_x = width // 2 + random.randint(-30, 30)
    start_y = int(height * 0.8) + random.randint(-20, 20)
    end_x = width // 2 + random.randint(-30, 30)
    end_y = int(height * 0.3) + random.randint(-20, 20)

    # 2. 确定控制点 (P1) - 决定曲线的弧度(偏移量按屏宽比例换算，适配不同分辨率)
    control_x = (start_x + end_x) // 2 + random.choice([-1, 1]) * int(width * random.uniform(0.05, 0.14))
    control_y = (start_y + end_y) // 2

    # 3. 低频平滑漂移参数：整条轨迹缓慢左右摆动(而非逐点抖动)
    drift_amp = random.uniform(2.0, 6.0)       # 漂移幅度(像素)
    drift_cycles = random.uniform(0.5, 1.5)    # 全程摆动 0.5~1.5 个周期
    drift_phase = random.uniform(0, math.pi * 2)

    # 4. 生成贝塞尔曲线上的点集
    points = []
    steps = random.randint(15, 25) # 将一次滑动拆分为 15-25 个微小动作

    for i in range(steps):
        t = i / (steps - 1)

        # 应用 Ease-In-Out 缓动函数让时间 t 产生变速效果 (类似于 S 型曲线)
        # 这样中间点密集，两头稀疏，模拟先加速后减速
        eased_t = t * t * (3 - 2 * t)

        # 贝塞尔曲线公式计算坐标
        x = (1 - eased_t)**2 * start_x + 2 * (1 - eased_t) * eased_t * control_x + eased_t**2 * end_x
        y = (1 - eased_t)**2 * start_y + 2 * (1 - eased_t) * eased_t * control_y + eased_t**2 * end_y

        # 低频平滑漂移(仅横向)
        x += drift_amp * math.sin(2 * math.pi * drift_cycles * t + drift_phase)

        # 偶发的 1 像素级微颤(约 20% 的点)
        if random.random() < 0.2:
            x += random.choice([-1, 0, 1])
            y += random.choice([-1, 0, 1])

        points.append((int(x), int(y)))

    # 5. 调用底层 API 逐点执行滑动(注入随机压力：基准随机 + 逐点微变，模拟真人按压力度变化)
    print(f"  [拟人滑动] 生成了 {len(points)} 个轨迹节点，开始执行贝塞尔滑动...")
    base_pressure = random.uniform(0.85, 1.0)

    # 按下起点
    touch_down(points[0][0], points[0][1], base_pressure)
    time.sleep(random.uniform(0.02, 0.05)) # 按下后稍微停顿

    # 划过中间点
    for point in points[1:]:
        pressure = min(1.0, max(0.8, base_pressure + random.uniform(-0.03, 0.03)))
        touch_move(point[0], point[1], pressure)
        # 每移动一个点，停留极短的时间 (10-30毫秒)
        time.sleep(random.uniform(0.01, 0.03))

    # 终点抬起
    touch_up(points[-1][0], points[-1][1])


def short_swipe():
    """短距离轻扫：只移动一小段距离，用于进入浏览页后触发倒计时开始"""
    start_x = screen_width // 2 + random.randint(-30, 30)
    start_y = int(screen_height * 0.60) + random.randint(-20, 20)
    end_x = start_x + random.randint(-10, 10)
    end_y = start_y - int(screen_height * random.uniform(0.06, 0.10)) # 只向上移动一小段(按屏高比例)
    duration = random.uniform(0.25, 0.45)
    d.swipe(start_x, start_y, end_x, end_y, duration)


# 触摸注入：u2 的 touch API 压力被硬编码为 0，这里直接调用底层接口以注入随机压力
# (注入事件的压力恒定是典型的机器特征，真人压力是持续变化的)
_TOUCH_DOWN, _TOUCH_UP, _TOUCH_MOVE = 0, 1, 2

def touch_down(x, y, pressure):
    try:
        d.jsonrpc.injectInputEvent(_TOUCH_DOWN, int(x), int(y), float(pressure))
    except Exception:
        d.touch.down(x, y)

def touch_move(x, y, pressure):
    try:
        d.jsonrpc.injectInputEvent(_TOUCH_MOVE, int(x), int(y), float(pressure))
    except Exception:
        d.touch.move(x, y)

def touch_up(x, y):
    try:
        d.jsonrpc.injectInputEvent(_TOUCH_UP, int(x), int(y), 0)
    except Exception:
        d.touch.up(x, y)

def human_click(x, y):
    """拟人化点击：偏移方向与大小、按压力度、按压时长均随机"""
    offset_x = x + random.choice([-1, 1]) * random.randint(3, 12)
    offset_y = y + random.choice([-1, 1]) * random.randint(3, 12)
    pressure = random.uniform(0.85, 1.0)   # 随机压力
    duration = random.uniform(0.06, 0.15)  # 随机按压时长
    touch_down(offset_x, offset_y, pressure)
    time.sleep(duration)
    touch_up(offset_x, offset_y)

# ==========================================
# 阶段 3：页面处理逻辑
# ==========================================

def handle_page_1(vision_data):
    """处理页面1：寻找匹配的'去完成'并点击。返回是否成功启动了任务。
    vision_data 为 None 时表示原生页面，直接用无障碍节点获取文本(比OCR快数倍)。"""
    print("  👁️ 视觉判断：当前处于 [页面1-任务大厅]")

    if vision_data is None:
        # 快速路径：原生页面用无障碍节点直接取任务与按钮
        browse_tasks = []
        buttons_go = []
        try:
            for kw in TASK_KEYWORDS:
                for el in d(textContains=kw):
                    info = el.info
                    bounds = info.get('bounds') or {}
                    browse_tasks.append({'text': info.get('text') or kw,
                                         'x': float(bounds.get('left', 0)),
                                         'y': float(bounds.get('top', 0))})
            for el in d(textContains="去完成"):
                info = el.info
                bounds = info.get('bounds') or {}
                buttons_go.append({'text': '去完成',
                                   'x': float(bounds.get('left', 0)),
                                   'y': float(bounds.get('top', 0))})
        except Exception as e:
            print(f"  ⚠️ 无障碍节点读取失败: {e}")
            browse_tasks, buttons_go = [], []
        log(f"页面1(u2路径): 浏览任务候选 {len(browse_tasks)} 个, 去完成按钮 {len(buttons_go)} 个")

        # 修复：u2 能看到页面标题但看不到任务列表(WebView/H5)时，回退全屏 OCR
        if not browse_tasks or not buttons_go:
            print("  ⚡ 无障碍节点未读到任务/按钮(任务列表可能是WebView)，回退全屏 OCR 扫描...")
            vision_data = get_screen_vision()
            browse_tasks = []
            buttons_go = []
            for item in vision_data:
                if is_browse_task_text(item['text']):
                    browse_tasks.append(item)
                if "去完成" in item['text']:
                    buttons_go.append(item)
            log(f"页面1(OCR回退): 浏览任务候选 {len(browse_tasks)} 个, 去完成按钮 {len(buttons_go)} 个")
    else:
        # 慢速路径：H5 页面，使用 OCR 识别结果
        browse_tasks = []
        buttons_go = []
        for item in vision_data:
            if is_browse_task_text(item['text']):
                browse_tasks.append(item)
            if "去完成" in item['text']:
                buttons_go.append(item)
        log(f"页面1(OCR路径): 浏览任务候选 {len(browse_tasks)} 个, 去完成按钮 {len(buttons_go)} 个")

    if not browse_tasks:
        log("页面1: 未发现任何浏览类任务文字")
        return False # 没找到任务，交给主循环处理

    # 逐个候选任务尝试匹配按钮：同一行内"浏览N秒"可能是已完成任务的描述行
    # (其按钮是"已完成"而非"去完成")，只有配得上"去完成"按钮的才是可做任务
    for target_task in browse_tasks:
        matched_button = None
        min_y_diff = None

        for btn in buttons_go:
            y_diff = abs(btn['y'] - target_task['y'])
            # 同一行判定(垂直距离 < 4% 屏高)与右侧按钮判定(x > 45% 屏宽)
            # 均按屏幕比例换算，适配不同分辨率
            if y_diff < screen_height * 0.04 and btn['x'] > screen_width * 0.45:
                if min_y_diff is None or y_diff < min_y_diff:
                    matched_button = btn
                    min_y_diff = y_diff

        if matched_button:
            print(f"  ✅ 成功匹配任务 '{target_task['text']}'，点击去完成...")
            log(f"任务匹配成功: '{target_task['text']}' y={target_task['y']:.0f} <-> 按钮y={matched_button['y']:.0f}")
            human_click(matched_button['x'], matched_button['y'])
            return True # 成功启动任务，后续跳转/执行由 execute_task_session 接管

    print(f"  ⚠️ 识别到 {len(browse_tasks)} 个浏览类任务文字，但均未匹配到'去完成'按钮（可能均已完成）")
    log("页面1: 所有候选任务均未匹配到'去完成'按钮(详见上方OCR记录)")
    return False # 所有候选都配不上按钮

def handle_page_2():
    """处理页面2：简单浏览，等待顶部出现'已得'"""
    print("  👁️ 视觉判断：当前处于 [页面2-常规浏览]")
    # 进入页面后先做一次短滑动，触发倒计时开始，再进入检测循环
    print("  👆 先做一次短滑动，触发浏览倒计时...")
    short_swipe()
    time.sleep(random.uniform(1.0, 2.0))

    start_time = time.time()

    while time.time() - start_time < 50: # 最多等待50秒
        is_completed = False

        # 快速路径：无障碍节点查询
        for kw in ["已得", "下单再得", "任务完成"]:
            if u2_region_exists(kw, 0.0, 0.2):
                is_completed = True
                break

        # 慢速路径：OCR 顶部 15% 区域兜底(每轮都做，防止完成文字
        # 只渲染在像素层而节点读不到导致盲等)
        if not is_completed:
            vision_data = get_screen_vision((0, 0, screen_width, int(screen_height * 0.15)))
            for item in vision_data:
                if "已得" in item['text'] or "下单再得" in item['text'] or is_task_done_text(item['text']):
                    is_completed = True
                    break

        # 执行期容错：已被自动送回任务大厅时直接结束本轮(不再按返回)
        if not is_completed:
            try:
                if d(textContains="做任务赚能量").exists or d(textContains="去完成").exists:
                    print("  🏠 检测到已回到任务大厅(任务可能已自动完成)，结束本轮。")
                    log("页面2: 执行期检测到任务大厅, 直接结束")
                    return
            except Exception:
                pass

        if is_completed:
            print("  ✅ 识别到'已得/下单再得'，任务完成，返回任务大厅。")
            return_to_task_hall()
            return

        # 尚未完成，继续拟人滑动浏览(保持页面活跃)
        print(f"  ⏳ 浏览中(已进行 {time.time() - start_time:.0f}/50秒)，继续滑动...")
        advanced_human_swipe(d)
        time.sleep(random.uniform(0.8, 1.6)) # 每轮间隔随机化

    print("  ⚠️ 50秒超时未检测到完成提示，强制返回任务大厅。")
    return_to_task_hall()

def handle_page_4():
    """处理页面4：带有右侧浮窗/底部进度条的页面(静止等待倒计时结束)"""
    print("  👁️ 视觉判断：当前处于 [页面4-浮窗等待]")
    start_time = time.time()

    # 先静止几秒让倒计时走起来(浮窗页面无需滑动)；5秒任务会在此期间完成
    time.sleep(random.uniform(5, 7))

    while time.time() - start_time < 30:
        is_completed = False

        # 快速路径：无障碍节点查询
        for kw in ["任务已完成", "任务完成", "完成", "已得"]:
            if u2_region_exists(kw, 0.5, 0.92):
                is_completed = True
                break

        # 慢速路径：OCR 50%~92% 区域兜底(每轮都做，防止完成文字
        # 只渲染在像素层而节点读不到导致盲等)
        if not is_completed:
            vision_data = get_screen_vision((0, int(screen_height * 0.5), screen_width, int(screen_height * 0.92)))
            for item in vision_data:
                if "完成" in item['text'] or "已得" in item['text']:
                    is_completed = True
                    break

        # 执行期容错：已被自动送回任务大厅时直接结束本轮(不再按返回)
        if not is_completed:
            try:
                if d(textContains="做任务赚能量").exists or d(textContains="去完成").exists:
                    print("  🏠 检测到已回到任务大厅(任务可能已自动完成)，结束本轮。")
                    log("页面4: 执行期检测到任务大厅, 直接结束")
                    return
            except Exception:
                pass

        if is_completed:
            print("  ✅ 浮窗状态变为已完成，返回任务大厅。")
            return_to_task_hall()
            return

        print(f"  ⏳ 尚未完成，继续等待(已等待 {time.time() - start_time:.0f}/30秒)...")
        time.sleep(random.uniform(1.5, 2.5)) # 等待间隔随机化

    print("  ⚠️ 30秒超时，强制返回任务大厅。")
    return_to_task_hall()

def handle_page_3():
    """处理页面3：搜索类页面(搜索福利/搜一搜)，点击关键词后进入浏览流程"""
    print("  👁️ 视觉判断：当前处于 [页面3-搜索页]")

    # 只在"历史搜索"与"搜索发现"板块区域内选择候选词，避免误点键盘或其它区域
    vision_data = get_screen_vision((0, 0, screen_width, int(screen_height * 0.75)))
    header_hist = next((i for i in vision_data if "历史搜索" in i['text']), None)
    header_disc = next((i for i in vision_data if "搜索发现" in i['text']), None)

    # 排除词：点击后会进入未知/无关页面的文字(如页面底部的"反馈"入口)
    EXCLUDE_WORDS = ("反馈",)

    def is_keyword_candidate(item):
        """候选词必须含汉字且长度>=2，排除数字键、单字符、板块标题及'反馈'等危险词"""
        text = item['text'].strip()
        if len(text) < 2 or "历史搜索" in text or "搜索发现" in text:
            return False
        if any(w in text for w in EXCLUDE_WORDS):
            return False
        return any('\u4e00' <= ch <= '\u9fff' for ch in text)

    search_candidates = []
    if header_hist or header_disc:
        # 板块区域：从"历史搜索"标题(或仅有"搜索发现"标题)到"搜索发现"标题下方约35%屏高
        zone_top = header_hist['y'] if header_hist else header_disc['y']
        zone_bottom = (header_disc['y'] if header_disc else zone_top) + screen_height * 0.35
        for item in vision_data:
            if zone_top < item['y'] < zone_bottom and is_keyword_candidate(item):
                search_candidates.append(item)
        print(f"  🎯 已锁定搜索词板块 (y {zone_top:.0f}~{zone_bottom:.0f})，候选 {len(search_candidates)} 个")
    else:
        # 未找到板块标题时的兜底：取屏幕 15%~70% 区域内含汉字的词
        for item in vision_data:
            if screen_height * 0.15 < item['y'] < screen_height * 0.70 and is_keyword_candidate(item):
                search_candidates.append(item)
        print(f"  ⚠️ 未找到'历史搜索/搜索发现'标题，使用区域兜底，候选 {len(search_candidates)} 个")

    max_attempts = 3 # 最多尝试点击3次

    for attempt in range(max_attempts):
        if search_candidates:
            # 从 AI 看到的词里随机挑一个来点，绝不会点空
            target = random.choice(search_candidates)
            print(f"  [尝试 {attempt+1}/{max_attempts}] 精准点击搜索词: '{target['text']}'")
            human_click(target['x'], target['y'])
        else:
            # 兜底策略：如果没识别到字，才使用区域盲点
            target_x = screen_width * random.uniform(0.2, 0.8)
            target_y = screen_height * random.uniform(0.2, 0.4)
            print(f"  [尝试 {attempt+1}/{max_attempts}] 盲点屏幕中上方区域...")
            human_click(target_x, target_y)

        # 给 APP 一点时间响应和加载新页面
        time.sleep(random.uniform(2, 4))

        # 重新获取视觉，验证点击关键词后进入了哪种浏览页面
        print("  ⏳ 正在校验页面跳转状态...")
        new_vision_data = get_screen_vision()
        page_entered = None

        for item in new_vision_data:
            text = item['text']
            y = item['y']
            # 页面2特征：顶部出现浏览倒计时横幅(浏览N秒...可领)
            if is_browse_task_text(text) and "可领" in text and y < screen_height * 0.2:
                page_entered = "PAGE2"
                break
            # 页面4特征：下半屏出现浏览倒计时浮窗或任务完成提示
            if (is_browse_task_text(text) or is_task_done_text(text)) and y > screen_height * 0.5:
                page_entered = "PAGE4"
                break

        if page_entered == "PAGE2":
            print("  ✅ 成功进入浏览任务页(顶部横幅型)，移交控制权！")
            handle_page_2()
            return # 执行完毕，安全退出当前函数，返回主循环
        elif page_entered == "PAGE4":
            print("  ✅ 成功进入浏览任务页(浮窗型)，移交控制权！")
            handle_page_4()
            return # 执行完毕，安全退出当前函数，返回主循环
        else:
            print("  ⚠️ 校验失败：未检测到浏览页特征，点击可能未生效或网络卡顿。")
            # 如果没有成功，循环会继续，进行下一次尝试点击

    # 如果 3 次尝试都失败了，进行容错退回，防止脚本卡死在这个页面
    print("  ❌ 多次尝试点击搜索均未触发任务，放弃当前任务，返回任务大厅。")
    return_to_task_hall()

# ==========================================
# 阶段 4：主脑循环
# ==========================================

def is_on_task_hall():
    """判断当前是否在任务大厅(页面1)。特征：'做任务赚能量'标题或'去完成'按钮，
    任一命中即认定(标题偶尔 OCR 漏读时，按钮可作为兜底特征)。
    优先无障碍节点，回退 OCR 全屏。"""
    try:
        if d(textContains="做任务赚能量").exists or d(textContains="去完成").exists:
            return True
    except Exception:
        pass
    vision_data = get_screen_vision()
    return any(("做任务赚能量" in i['text']) or ("去完成" in i['text'])
               for i in vision_data)

def is_on_page0():
    """判断是否在页面0(任务大厅的上级页面)。特征：'去赚能量'或'升级赛车拿钱'。"""
    try:
        if d(textContains="去赚能量").exists or d(textContains="升级赛车拿钱").exists:
            return True
    except Exception:
        pass
    vision_data = get_screen_vision()
    return any(("去赚能量" in i['text']) or ("升级赛车拿钱" in i['text'])
               for i in vision_data)

def click_go_earn_energy():
    """点击页面0的'去赚能量'，进入任务大厅。返回是否成功点击。"""
    # 优先无障碍节点(点击元素中心)
    try:
        els = d(textContains="去赚能量")
        if els.exists:
            bounds = els[0].info.get('bounds') or {}
            cx = (bounds.get('left', 0) + bounds.get('right', 0)) / 2
            cy = (bounds.get('top', 0) + bounds.get('bottom', 0)) / 2
            human_click(cx, cy)
            log("页面0: 点击'去赚能量'(u2)")
            return True
    except Exception:
        pass
    # OCR 回退：点击'去赚能量'文字所在位置
    vision_data = get_screen_vision()
    for item in vision_data:
        if "去赚能量" in item['text']:
            human_click(item['x'] + 20, item['y'] + 10)
            log(f"页面0: 点击'去赚能量'(OCR, 命中'{item['text']}')")
            return True
    return False

def wait_for_task_hall(max_wait=15):
    """初始状态检查：等待手机停留在任务大厅。
    若在页面0则自动点击'去赚能量'进入大厅；超时仍未见到大厅返回 False。"""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        print(f"  ⏳ 初始状态: 等待任务大厅页面(已等 {time.time() - start_time:.0f}/{max_wait}秒)...")
        if is_on_task_hall():
            print("  ✅ 已停留在任务大厅，开始查找任务")
            log("初始状态: 已在任务大厅")
            return True
        if is_on_page0():
            print("  🔄 当前在页面0(大厅上级页)，点击'去赚能量'进入任务大厅...")
            if click_go_earn_energy():
                time.sleep(random.uniform(2, 4))
                continue
        time.sleep(random.uniform(1.5, 2.5))
    return False

def return_to_task_hall(max_back_attempts=3):
    """返回任务大厅：先检查是否已在大厅(避免在大厅上多按返回反而退出大厅)，
    不在大厅时逐步按返回键，每次后随机等待并重新识别，直到回到大厅。
    最多按 max_back_attempts 次，仍回不到大厅则退出脚本。"""
    for attempt in range(max_back_attempts + 1):
        if is_on_task_hall():
            if attempt > 0:
                print("  ✅ 已回到任务大厅")
            log(f"返回大厅: 成功(第{attempt}次返回后)" if attempt > 0 else "返回大厅: 已在大厅, 无需返回")
            return True
        if attempt == max_back_attempts:
            break
        print(f"  🔙 返回任务大厅: 第 {attempt+1}/{max_back_attempts} 次按返回键...")
        log(f"返回大厅: 第 {attempt+1} 次按返回键")
        d.press("back")
        time.sleep(random.uniform(1.5, 2.5))

    print("  ❌ 连续多次返回仍未回到任务大厅，为避免误操作，脚本退出。")
    log("返回大厅: 多次返回失败，脚本退出")
    print("=" * 40)
    exit()

def classify_page():
    """页面路由判定：优先用无障碍节点查询(原生页面约0.1~0.3秒/次且文本精确)，
    查不到特征时回退到全屏 OCR(兼容 H5 页面)。
    返回 (页面类型, OCR识别数据)；走快速路径时第二个返回值为 None。"""
    # --- 快速路径：无障碍节点 ---
    try:
        # 大厅特征：标题或'去完成'按钮(标题漏读时按钮兜底，防止误判成页面4)
        if d(textContains="做任务赚能量").exists or d(textContains="去完成").exists:
            log("路由判定: PAGE1 (u2快速路径)")
            return "PAGE1", None
        # 页面0特征：'去赚能量'或'升级赛车拿钱'
        if d(textContains="去赚能量").exists or d(textContains="升级赛车拿钱").exists:
            log("路由判定: PAGE0 (u2快速路径)")
            return "PAGE0", None
        for kw in PAGE3_KEYWORDS:
            if d(textContains=kw).exists:
                log(f"路由判定: PAGE3 (u2快速路径, 命中'{kw}')")
                return "PAGE3", None
        if u2_region_exists("可领", 0.0, 0.2):
            log("路由判定: PAGE2 (u2快速路径)")
            return "PAGE2", None
        for kw in TASK_KEYWORDS:
            if u2_region_exists(kw, 0.5, 1.0):
                log(f"路由判定: PAGE4 (u2快速路径, 命中'{kw}')")
                return "PAGE4", None
        # 底部/浮窗显示"任务完成(已)"的页面也按页面4处理(会立即检测到完成并返回)
        for done_kw in ["任务已完成", "任务完成"]:
            if u2_region_exists(done_kw, 0.5, 1.0):
                log(f"路由判定: PAGE4 (u2快速路径, 命中'{done_kw}')")
                return "PAGE4", None
    except Exception:
        pass

    # --- 慢速路径：全屏 OCR ---
    vision_data = get_screen_vision()
    for item in vision_data:
        text = item['text']
        y = item['y']
        if "做任务赚能量" in text or "去完成" in text:
            log(f"路由判定: PAGE1 (OCR路径, 命中'{text}')")
            return "PAGE1", vision_data
        if "去赚能量" in text or "升级赛车拿钱" in text:
            log(f"路由判定: PAGE0 (OCR路径, 命中'{text}')")
            return "PAGE0", vision_data
        if is_page3_text(text):
            log(f"路由判定: PAGE3 (OCR路径, 命中'{text}')")
            return "PAGE3", vision_data
        if is_browse_task_text(text) and "可领" in text and y < screen_height * 0.2:
            log(f"路由判定: PAGE2 (OCR路径, 命中'{text}')")
            return "PAGE2", vision_data
        if is_browse_task_text(text) and y > screen_height * 0.5:
            log(f"路由判定: PAGE4 (OCR路径, 命中'{text}')")
            return "PAGE4", vision_data
        if is_task_done_text(text) and y > screen_height * 0.5:
            log(f"路由判定: PAGE4 (OCR路径, 命中'{text}')")
            return "PAGE4", vision_data
    log("路由判定: UNKNOWN (OCR未命中任何页面特征)")
    return "UNKNOWN", vision_data

def execute_task_session():
    """完整任务会话：前往执行状态 → 执行状态 → 返回任务大厅。
    [前往执行] 点击'去完成'后确认已离开大厅，并识别进入的是哪种任务页面；
    [执行] 移交给对应的页面处理函数(内部完成后会自动返回大厅)；
    状态与页面不匹配时按容错规则处理。"""
    print("  ➡️ [前往执行状态] 等待页面跳转...")
    target_page = None
    start_time = time.time()

    while time.time() - start_time < 15: # 最多等15秒页面跳转
        time.sleep(random.uniform(1.0, 2.0)) # 轮询间隔随机化
        print(f"  ⏳ 等待页面跳转(已等 {time.time() - start_time:.0f}/15秒)...")
        page_type, _ = classify_page()

        if page_type == "PAGE1":
            continue # 仍在大厅，点击可能尚未生效，继续等待
        if page_type == "PAGE0":
            # 意外进入页面0：点'去赚能量'回大厅，本轮任务作废
            print("  🔄 意外进入页面0，点击'去赚能量'回到任务大厅，重新查找任务。")
            click_go_earn_energy()
            time.sleep(random.uniform(2, 4))
            return
        if page_type in ("PAGE2", "PAGE3", "PAGE4"):
            target_page = page_type
            break
        # UNKNOWN: 页面加载/跳转中，继续等待

    if target_page is None:
        # 超时仍未进入已知任务页：再确认一次是否仍在大厅
        page_type, _ = classify_page()
        if page_type == "PAGE1":
            print("  ⚠️ 点击后仍停留在任务大厅(点击可能未生效)，重新查找任务。")
            log("前往执行: 超时仍在大厅, 重新查找任务")
            return
        print("  ⚠️ 点击后进入未知页面，按返回键尝试回到任务大厅...")
        return_to_task_hall() # 3次返回失败会退出脚本
        return

    # ---- 执行状态：移交给对应处理函数 ----
    if target_page == "PAGE2":
        print("  ✅ [执行状态] 进入页面2-常规浏览")
        handle_page_2()
    elif target_page == "PAGE3":
        print("  ✅ [执行状态] 进入页面3-搜索页")
        handle_page_3()
    elif target_page == "PAGE4":
        print("  ✅ [执行状态] 进入页面4-浮窗浏览")
        handle_page_4()

def main_loop():
    print(f"\n🚀 启动自动化引擎...")
    d.app_start(TARGET_APP_PACKAGE)
    time.sleep(random.uniform(4, 6)) # 启动等待随机化

    # ========== 初始状态：必须停留在任务大厅(页面0可自动进入) ==========
    if not wait_for_task_hall(max_wait=15):
        print("\n" + "="*40)
        print("❌ 启动后未检测到任务大厅(页面1)，也不在页面0。")
        print("   请手动将手机停在任务大厅页面后重新运行脚本。")
        print("="*40)
        log("初始状态: 未找到任务大厅, 脚本退出")
        return

    task_count = 0        # 总完成计数
    empty_streak = 0      # 连续未发现任务次数
    max_empty_streak = 3  # 如果连续3次扫描+滑动都没任务，就退出

    # ========== 大厅状态主循环：找任务 → 前往执行 → 执行 → 返回大厅 ==========
    while True:
        print(f"\n--- [正在扫描屏幕...] ---")
        page_type, vision_data = classify_page()

        if page_type == "PAGE1":
            success = handle_page_1(vision_data)
            if success:
                task_count += 1
                empty_streak = 0 # 只要做成了一个，重置"落空"计数
                # 前往执行状态→执行状态→返回大厅(内部含容错)
                execute_task_session()
                # 任务间随机休息，模拟真人做任务的节奏(偶尔来一次长休息)
                rest = random.uniform(2.0, 6.0)
                if random.random() < 0.15:
                    rest = random.uniform(15.0, 30.0)
                print(f"  ☕ 任务间休息 {rest:.1f} 秒后继续...")
                log(f"任务节奏: 休息{rest:.1f}秒")
                time.sleep(rest)
            else:
                empty_streak += 1
                print(f"  📍 当前页面未发现可做任务，尝试滑动寻找 (连续第 {empty_streak} 次)")
                advanced_human_swipe(d)
                time.sleep(random.uniform(1.5, 2.5))

                if empty_streak >= max_empty_streak:
                    print("\n" + "="*40)
                    print("🏁 【任务已全部完成】")
                    print(f"检测到主页已无浏览类(15秒/5秒)任务（连续{max_empty_streak}次扫描未发现）。")
                    print(f"本次运行共计完成任务数: {task_count} 个")
                    print("="*40)
                    break # 退出主循环

        elif page_type == "PAGE0":
            # 状态与页面不匹配：大厅循环中却发现自己在页面0
            print("  🔄 检测到页面0(大厅上级页)，点击'去赚能量'回到任务大厅...")
            click_go_earn_energy()
            time.sleep(random.uniform(2, 4))

        else:
            # 状态与页面不匹配：大厅循环中却检测到其它/未知页面 → 按返回尝试回大厅
            print("  ❓ 当前不在任务大厅(状态异常)，按返回键尝试回到任务大厅...")
            return_to_task_hall() # 已在大厅会直接返回；3次失败内部退出

if __name__ == '__main__':
    main_loop()
    # 运行结束后清理截图文件
    if os.path.exists("temp_screen.png"):
        os.remove("temp_screen.png")
