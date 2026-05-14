###################################
# 使用说明：用于自动完成tb的618淘金币活动浏览任务，只会完成浏览15秒的任务，其他任务不会管。
# 启动脚本前需要先将手机停留在“做任务赚体力”界面，然后在powershell下执行 python .\auto_browers.py 启动脚本，脚本会自动读取手机屏幕并识别页面中的浏览15秒任务，智能点击，并进行滑动和等待。完成所有浏览任务后会自动退出，并显示总完成数。可通过ctrl+C中断脚本。
# 执行之前需要在手机上开启USB调试，并允许点击、滑动操作，并连接到电脑。电脑上需要安装uiautomator2，cnocr等Python库后方可使用。
# 
# !!!注意事项!!!
# 1、此脚本仅供学习和研究使用，请勿用于商业用途或违反相关平台规则。使用前请确保了解相关风险，并自行承担责任。
# 2、由于本脚本完全根据固定逻辑执行任务，如果任务界面、需求、关键词等元素出现更新，可能导致脚本失效。
# 3、考虑到本脚本未对不同手机做兼容性测试，可能在不同设备上执行情况有区别，建议在执行时密切关注手机上显示的实际结果，确保脚本行为符合预期。
###################################

import uiautomator2 as u2
from cnocr import CnOcr
import time
import random
import os
import math

# ==========================================
# 阶段 1：初始化与全局配置
# ==========================================
TARGET_APP_PACKAGE = "com.taobao.taobao" 

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
# 阶段 2：视觉与动作核心函数
# ==========================================

def get_screen_vision():
    """截取全屏并返回 OCR 识别结果"""
    screenshot_path = "temp_screen.png"
    d.screenshot(screenshot_path)
    result = ocr.ocr(screenshot_path)
    
    # 提取并整理识别结果为更好用的格式
    vision_data = []
    for item in result:
        text = item['text']
        # 取左上角的 X 和 Y 坐标
        x = float(item['position'][0][0])
        y = float(item['position'][0][1])
        vision_data.append({"text": text, "x": x, "y": y})
        
    return vision_data

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
    终极拟人化滑动：贝塞尔曲线轨迹 + 缓动变速 + 随机微小抖动
    """
    width, height = device.window_size()
    
    # 1. 确定起点 (P0) 和终点 (P2)
    start_x = width // 2 + random.randint(-30, 30)
    start_y = int(height * 0.8) + random.randint(-20, 20)
    end_x = width // 2 + random.randint(-30, 30)
    end_y = int(height * 0.3) + random.randint(-20, 20)
    
    # 2. 确定控制点 (P1) - 决定曲线的弧度
    # 人的大拇指通常往内侧弯，所以我们在 X 轴上给一个较大的偏移量来形成弧线
    control_x = (start_x + end_x) // 2 + random.choice([-1, 1]) * random.randint(50, 150)
    control_y = (start_y + end_y) // 2 
    
    # 3. 生成贝塞尔曲线上的点集
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
        
        # 加上1-2个像素的随机抖动，模拟肌肉颤抖
        noise_x = random.randint(-2, 2)
        noise_y = random.randint(-2, 2)
        
        points.append((int(x + noise_x), int(y + noise_y)))

    # 4. 调用底层 API 逐点执行滑动
    print(f"  [高阶拟人滑动] 生成了 {len(points)} 个轨迹节点，开始执行贝塞尔滑动...")
    
    # 按下起点
    device.touch.down(points[0][0], points[0][1])
    time.sleep(random.uniform(0.02, 0.05)) # 按下后稍微停顿
    
    # 划过中间点
    for point in points[1:]:
        device.touch.move(point[0], point[1])
        # 每移动一个点，停留极短的时间 (10-30毫秒)
        time.sleep(random.uniform(0.01, 0.03)) 
        
    # 终点抬起
    device.touch.up(points[-1][0], points[-1][1])


def human_click(x, y):
    """加入少许随机偏移的拟人化点击"""
    offset_x = x + random.randint(5, 15)
    offset_y = y + random.randint(5, 15)
    d.click(offset_x, offset_y)

# ==========================================
# 阶段 3：页面处理逻辑
# ==========================================

def handle_page_1(vision_data):
    """处理页面1：寻找匹配的'去完成'并点击。返回是否成功启动了任务。"""
    print("  👁️ 视觉判断：当前处于 [页面1-任务大厅]")
    
    tasks_15s = []
    buttons_go = []
    
    for item in vision_data:
        if "浏览15秒" in item['text']:
            tasks_15s.append(item)
        if "去完成" in item['text']:
            buttons_go.append(item)
            
    if not tasks_15s:
        return False # 没找到任务，交给主循环处理

    target_task = tasks_15s[0]
    matched_button = None
    
    for btn in buttons_go:
        y_diff = abs(btn['y'] - target_task['y'])
        if y_diff < 80 and btn['x'] > 500:
            matched_button = btn
            break
            
    if matched_button:
        print(f"  ✅ 成功匹配任务！点击去完成...")
        human_click(matched_button['x'], matched_button['y'])
        time.sleep(random.uniform(3, 5))
        return True # 成功启动任务
    else:
        return False # 没匹配到按钮

def handle_page_2():
    """处理页面2：简单浏览，等待顶部出现'已得'"""
    print("  👁️ 视觉判断：当前处于 [页面2-常规浏览]")
    start_time = time.time()
    
    while time.time() - start_time < 50: # 最多等待50秒
        advanced_human_swipe(d)
        time.sleep(random.uniform(0.5, 1.0))
        
        # 滑动后截取全屏检查是否完成
        vision_data = get_screen_vision()
        is_completed = False
        
        for item in vision_data:
            # 限制在屏幕顶部 15% 区域内寻找关键词
            if item['y'] < screen_height * 0.15:
                if "已得" in item['text'] or "下单再得" in item['text']:
                    is_completed = True
                    break
                    
        if is_completed:
            print("  ✅ 识别到'已得/下单再得'，任务完成，返回主页。")
            d.press("back")
            time.sleep(random.uniform(2, 3))
            return
            
    print("  ⚠️ 50秒超时未检测到完成提示，强制返回。")
    d.press("back")
    time.sleep(2)

def handle_page_4():
    """处理页面4：带有右侧浮窗的页面"""
    print("  👁️ 视觉判断：当前处于 [页面4-浮窗等待]")
    start_time = time.time()
    
    # 静止等待 15 秒左右
    time.sleep(15)
    
    while time.time() - start_time < 25:
        vision_data = get_screen_vision()
        is_completed = False
        
        for item in vision_data:
            # 限制在屏幕中下部寻找 (50% ~ 80%)
            if screen_height * 0.5 < item['y'] < screen_height * 0.8:
                if "完成" in item['text'] or "已得" in item['text']:
                    is_completed = True
                    break
                    
        if is_completed:
            print("  ✅ 浮窗状态变为已完成，返回主页。")
            d.press("back")
            time.sleep(random.uniform(2, 3))
            return
            
        print("  ⏳ 尚未完成，继续等待 2 秒...")
        time.sleep(2)
        
    print("  ⚠️ 25秒超时，强制返回。")
    d.press("back")
    time.sleep(2)

def handle_page_3(vision_data):
    """处理页面3：搜索福利 (包含智能点击与状态校验)"""
    print("  👁️ 视觉判断：当前处于 [页面3-搜索福利]")
    
    # 1. 智能提取搜索词坐标
    # 策略：排除掉顶部的标题 (Y < 15%)，剩下的居中文字大概率都是可点击的商品/搜索标签
    search_candidates = []
    for item in vision_data:
        if screen_height * 0.15 < item['y'] < screen_height * 0.7:
            search_candidates.append(item)
            
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
        
        # 2. 核心改进：重新获取视觉，验证是否真的跳到了页面 2
        print("  ⏳ 正在校验页面跳转状态...")
        new_vision_data = get_screen_vision()
        is_page_2 = False
        
        for item in new_vision_data:
            # 校验页面 2 的核心特征 (使用 "浏览15" 增加 OCR 容错率)
            if "浏览15" in item['text'] and item['y'] < screen_height * 0.2:
                is_page_2 = True
                break
                
        if is_page_2:
            print("  ✅ 成功进入浏览任务页，移交控制权！")
            # 确定成功后，直接调用处理页面2的函数
            handle_page_2()
            return # 执行完毕，安全退出当前函数，返回主循环
        else:
            print("  ⚠️ 校验失败：未检测到页面2特征，点击可能未生效或网络卡顿。")
            # 如果没有成功，循环会继续，进行下一次尝试点击
            
    # 如果 3 次尝试都失败了，进行容错退回，防止脚本卡死在这个页面
    print("  ❌ 多次尝试点击搜索均未触发任务，放弃当前任务，返回主页。")
    d.press("back")
    time.sleep(2)

# ==========================================
# 主脑循环
# ==========================================

def main_loop():
    print(f"\n🚀 启动自动化引擎...")
    d.app_start(TARGET_APP_PACKAGE)
    time.sleep(5)
    
    task_count = 0        # 总完成计数
    empty_streak = 0      # 连续未发现任务次数
    max_empty_streak = 3  # 如果连续3次扫描+滑动都没任务，就退出

    while True:
        print(f"\n--- [正在扫描屏幕...] ---")
        vision_data = get_screen_vision()
        
        # 页面路由判定
        page_type = "UNKNOWN"
        for item in vision_data:
            text = item['text']
            y = item['y']
            if "做任务赚体力" in text:
                page_type = "PAGE1"
                break
            elif "搜索有福利" in text:
                page_type = "PAGE3"
                break
            elif "浏览15秒可领" in text and y < screen_height * 0.2:
                page_type = "PAGE2"
                break
            elif "浏览15秒" in text and y > screen_height * 0.5:
                page_type = "PAGE4" 
                
        # 执行路由
        if page_type == "PAGE1":
            success = handle_page_1(vision_data)
            if success:
                task_count += 1
                empty_streak = 0 # 只要做成了一个，重置“落空”计数
            else:
                empty_streak += 1
                print(f"  📍 当前页面未发现可做任务，尝试滑动寻找 (连续第 {empty_streak} 次)")
                advanced_human_swipe(d)
                time.sleep(2)
                
                if empty_streak >= max_empty_streak:
                    print("\n" + "="*40)
                    print("🏁 【任务已全部完成】")
                    print(f"检测到主页已无'浏览15秒'任务（连续{max_empty_streak}次扫描未发现）。")
                    print(f"本次运行共计完成任务数: {task_count} 个")
                    print("="*40)
                    break # 退出主循环
                    
        elif page_type == "PAGE2":
            handle_page_2()
        elif page_type == "PAGE3":
            handle_page_3(vision_data)
        elif page_type == "PAGE4":
            handle_page_4()
        else:
            print("  🤔 无法识别当前页面，尝试滑动刷新...")
            advanced_human_swipe(d)
            time.sleep(3)

if __name__ == '__main__':
    main_loop()
    # 运行结束后清理截图文件
    if os.path.exists("temp_screen.png"):
        os.remove("temp_screen.png")