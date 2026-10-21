"""活动页升级挂机脚本：长按页面上的升级按钮消耗能量升级。
长按升级后偶发'解锁新装备'弹窗，脚本会自动点击'确认选择'或关闭'X'后继续。

使用说明：
1. 手机开启 USB 调试并连接电脑(ATX 服务由 uiautomator2 自动维护)。
2. 手机停留在活动首页(能看到升级按钮)。
3. 激活虚拟环境后运行: python auto_upgrade.py [能量阈值]
   - 能量阈值(可选)：剩余能量低于该值时停止升级，不填默认 5000
   - 示例: python auto_upgrade.py        (阈值 5000)
           python auto_upgrade.py 3000   (阈值 3000)
"""
import uiautomator2 as u2
from cnocr import CnOcr
import time
import random
import re
import os
import sys

# 将单次 jsonrpc 调用的默认超时从 300 秒降到 20 秒：
# 设备端服务劣化(查询挂死)时快速失败，避免脚本长时间卡死
import uiautomator2.base as _u2base
_u2base.HTTP_TIMEOUT = 20

# ==========================================
# 日志系统(与 auto_browers.py 相同方案)：
# 控制台输出全程留档 + OCR 识别结果逐条记录，固定文件名自动覆盖
# ==========================================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "use_energy.log")
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

# 随机种子：每次运行随机生成并打印；需要复现本次行为时可 random.seed(同值)
RANDOM_SEED = random.randrange(10 ** 8)
random.seed(RANDOM_SEED)
print(f"📝 本次运行日志(自动覆盖上次): {LOG_FILE}")
print(f"🎲 本次随机种子: {RANDOM_SEED}")
log(f"===== 运行开始 {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
log(f"随机种子: {RANDOM_SEED}")

# ==========================================
# 初始化
# ==========================================
print("正在加载 AI 视觉模型...")
ocr = CnOcr()

print("正在连接手机...")
try:
    d = u2.connect()
    screen_width, screen_height = d.window_size()
    print(f"成功连接设备。屏幕尺寸: 宽 {screen_width} x 高 {screen_height}")
except Exception as e:
    print(f"手机连接失败: {e}")
    exit()

# ==========================================
# 触摸注入(随机压力)：u2 的 touch API 压力被硬编码为 0，
# 直接调用底层接口注入随机压力(真人压力是持续变化的)
# ==========================================
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

def get_screen_vision():
    """截取全屏并返回 OCR 识别结果(全部写入日志便于排查)"""
    screenshot_path = "temp_jump_screen.png"
    d.screenshot(screenshot_path)
    result = ocr.ocr(screenshot_path)

    vision_data = []
    for item in result:
        text = item['text']
        x = float(item['position'][0][0])
        y = float(item['position'][0][1])
        vision_data.append({"text": text, "x": x, "y": y})

    log(f"OCR识别 {len(vision_data)} 项:")
    for it in vision_data:
        log(f"    y={it['y']:7.1f} x={it['x']:7.1f} | {it['text']}")
    return vision_data

# ==========================================
# '解锁新涂装'弹窗检测与关闭
# ==========================================
# 弹窗特征文字(命中任一即认定弹窗出现)：覆盖'解锁新涂装'/'解锁新尾翼'等变体
POPUP_SIGNATURES = ["解锁新", "确认选择", "点击关闭将随机"]

def handle_popup_if_any(vision_data):
    """检测并关闭'解锁新涂装/尾翼'弹窗。返回是否处理了弹窗。
    优先点击弹窗中的'确认选择'按钮；找不到时点击弹窗下方的'X'关闭。"""
    has_popup = any(any(kw in i['text'] for kw in POPUP_SIGNATURES)
                    for i in vision_data)
    if not has_popup:
        return False

    print("  🔔 检测到'解锁新装备'弹窗，正在关闭...")
    log("弹窗: 检测到'解锁新装备'弹窗")

    # 优先：点击'确认选择'按钮。
    # ⚠️ 弹窗说明文字"…确认选择后不可修改…"同样包含这四个字，必须排除——
    # 取所有命中项中【文字最短】的那个(独立按钮只有4个字，说明文字有20+字)
    confirm_candidates = [i for i in vision_data if "确认选择" in i['text']]
    if confirm_candidates:
        btn = min(confirm_candidates, key=lambda i: len(i['text'].strip()))
        click_x = btn['x'] + screen_width * 0.035
        click_y = btn['y'] + screen_height * 0.008
        print(f"  👉 点击'确认选择'按钮 (x={click_x:.0f}, y={click_y:.0f}, 按钮文字'{btn['text']}')")
        log(f"弹窗: 点击'确认选择' ({click_x:.0f},{click_y:.0f}, 文字'{btn['text']}')")
        human_click(click_x, click_y)  # 点到按钮中部
        time.sleep(random.uniform(1.5, 2.5))  # 等待弹窗消失
        return True

    # 兜底1：点击独立的'X'关闭字符(弹窗底部，单个字符，避开说明文字)
    for item in vision_data:
        if item['text'].strip() in ("X", "x", "×", "✕") and item['y'] > screen_height * 0.5:
            print(f"  👉 点击弹窗关闭'X' (x={item['x']:.0f}, y={item['y']:.0f})")
            log(f"弹窗: 点击'X'关闭 ({item['x']:.0f},{item['y']:.0f})")
            human_click(item['x'] + 8, item['y'] + 8)
            time.sleep(random.uniform(1.5, 2.5))  # 等待弹窗消失
            return True

    # 兜底2：按'点击关闭将随机…'提示文字的屏幕比例偏移定位'X'
    for item in vision_data:
        if "点击关闭" in item['text']:
            x_close = item['x'] + screen_width * 0.15
            y_close = item['y'] + screen_height * 0.045
            print(f"  👉 点击弹窗关闭'X' (x={x_close:.0f}, y={y_close:.0f}, 按提示文字定位)")
            log(f"弹窗: 点击'X'关闭 ({x_close:.0f},{y_close:.0f}, 按提示文字定位)")
            human_click(x_close, y_close)
            time.sleep(random.uniform(1.5, 2.5))  # 等待弹窗消失
            return True

    print("  ⚠️ 识别到弹窗特征但未找到'确认选择'/'X'，稍后重扫...")
    log("弹窗: 未找到关闭按钮")
    time.sleep(random.uniform(1.5, 2.5))
    return True  # 已判定有弹窗，本轮不再执行长按，回到循环重新扫描

# ==========================================
# 升级主循环
# ==========================================
def start_jump_loop():
    """长按升级按钮消耗能量的挂机循环"""
    # 能量阈值：剩余能量低于该值时停止升级；命令行第1个参数可指定，默认 5000
    try:
        energy_threshold = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    except ValueError:
        print(f"⚠️ 无效的能量阈值参数 '{sys.argv[1]}'，使用默认值 5000")
        energy_threshold = 5000
    print("\n🚀 开始执行升级挂机任务...")
    print(f"  ⚙️ 能量阈值: {energy_threshold} (剩余能量低于该值将停止升级)")
    jump_count = 0
    fail_streak = 0          # 连续未检测到按钮的次数
    max_fail_streak = 5      # 连续5次按钮缺失则退出
    popup_close_attempts = 0 # 连续关闭弹窗的尝试次数(容错：两次点不掉则退出)

    while True:
        print(f"\n--- [第 {jump_count + 1} 次检查] 正在扫描屏幕 ---")
        vision_data = get_screen_vision()

        # 1. 弹窗检测与关闭(长按升级后偶发，遮挡主按钮)
        if handle_popup_if_any(vision_data):
            popup_close_attempts += 1
            if popup_close_attempts > 2:
                # 已点击关闭两次弹窗仍未消失(未回到正常页面0)，退出避免误操作
                print("\n" + "=" * 40)
                print("❌ 连续两次关闭弹窗后仍未回到页面0，脚本退出。")
                print("   请手动检查手机屏幕(弹窗类型可能与预期不同)。")
                print(f"本次运行共计执行长按升级: {jump_count} 次")
                print("=" * 40)
                log("弹窗容错: 连续两次关闭失败, 脚本退出")
                break
            continue  # 关闭后重新扫描
        popup_close_attempts = 0  # 弹窗已消失(回到正常页面0)，重置计数

        btn_item = None
        current_stamina = None

        # 2. 解析屏幕内容：按钮位置与剩余能量
        for item in vision_data:
            text = item['text']
            if "升级赛车拿钱" in text:
                btn_item = item
            if "剩余" in text and "能量" in text:
                digits = re.findall(r'\d+', text)
                if digits:
                    current_stamina = int(digits[0])

        # 3. 按钮缺失保护(弹窗已排除后仍缺失，可能是页面加载/遮挡)
        if btn_item is None:
            fail_streak += 1
            print(f"  ⚠️ 未检测到'升级赛车拿钱'按钮(连续第 {fail_streak}/{max_fail_streak} 次)，稍后重扫...")
            log(f"按钮缺失: 连续第 {fail_streak} 次")
            if fail_streak >= max_fail_streak:
                print("\n" + "=" * 40)
                print("❌ 连续多次未检测到按钮，可能已离开页面0，脚本退出。")
                print(f"本次运行共计执行长按升级: {jump_count} 次")
                print("=" * 40)
                break
            time.sleep(random.uniform(2.0, 4.0))
            continue
        fail_streak = 0

        # 4. 能量值判断
        if current_stamina is not None:
            print(f"  🔋 识别到当前能量值: {current_stamina}")
            if current_stamina < energy_threshold:
                print("\n" + "=" * 40)
                print(f"🏁 【任务结束】当前能量 ({current_stamina}) 已低于阈值 {energy_threshold}。")
                print(f"本次运行共计执行长按升级: {jump_count} 次")
                print("=" * 40)
                break
        else:
            print("  ⚠️ 未能清晰识别出能量数字，但按钮存在，继续尝试...")

        # 5. 执行长按连跳(随机偏移 + 随机压力 + 随机时长)
        click_x, click_y = btn_item['x'], btn_item['y']
        press_duration = random.uniform(3.2, 3.8)
        offset_x = click_x + random.choice([-1, 1]) * random.randint(3, 12)
        offset_y = click_y + random.choice([-1, 1]) * random.randint(3, 12)
        pressure = random.uniform(0.85, 1.0)

        print(f"  👆 物理长按: 坐标({offset_x:.0f}, {offset_y:.0f})，压力{pressure:.2f}，持续 {press_duration:.2f} 秒...")
        log(f"长按: ({offset_x:.0f},{offset_y:.0f}) 压力{pressure:.2f} {press_duration:.2f}秒")
        touch_down(offset_x, offset_y, pressure)
        time.sleep(press_duration)
        touch_up(offset_x, offset_y)
        jump_count += 1

        # 6. 连跳后的动画等待
        print("  ⏳ 等待连跳动画结算...")
        time.sleep(random.uniform(4.0, 5.0))
        # 动画结束后循环自动重新开始；若结算出了弹窗，下一轮循环开头会被检测并关闭

if __name__ == '__main__':
    start_jump_loop()

    # 运行结束后清理截图文件
    if os.path.exists("temp_jump_screen.png"):
        os.remove("temp_jump_screen.png")
