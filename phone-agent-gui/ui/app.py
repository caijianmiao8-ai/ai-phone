"""
Gradio UI 主界面
Phone Agent GUI 的主要用户界面
"""
import gradio as gr
import threading
import time
import io
import os
import shutil
import tempfile
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from PIL import Image
from typing import Optional, List, Tuple, Generator, Dict, Any, Union

from config.settings import Settings, get_settings, save_settings
from knowledge_base.manager import KnowledgeManager
from core.device_manager import DeviceManager, DeviceInfo
from core.device_registry import DeviceRegistry
from core.file_transfer import FileTransferManager, FileInfo, FileType
from core.adb_helper import ADBHelper
from core.agent_wrapper import AgentWrapper, TaskResult
from core.assistant_planner import AssistantPlanner, StructuredPlan
from core.scheduler import SchedulerManager, JobSpec


# 配置 Gradio 缓存目录
GRADIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "phone_agent_gradio_cache")


def clear_gradio_cache():
    """清理 Gradio 缓存目录"""
    try:
        # 清理自定义缓存目录
        if os.path.exists(GRADIO_CACHE_DIR):
            shutil.rmtree(GRADIO_CACHE_DIR, ignore_errors=True)
            os.makedirs(GRADIO_CACHE_DIR, exist_ok=True)

        # 清理默认 Gradio 缓存
        default_cache = os.path.join(tempfile.gettempdir(), "gradio")
        if os.path.exists(default_cache):
            # 只删除超过1小时的文件
            now = time.time()
            for root, dirs, files in os.walk(default_cache):
                for f in files:
                    filepath = os.path.join(root, f)
                    try:
                        if now - os.path.getmtime(filepath) > 3600:  # 1小时
                            os.remove(filepath)
                    except Exception:
                        pass
        return True
    except Exception:
        return False


# 全局状态
@dataclass
class DeviceTaskState:
    logs: List[str] = field(default_factory=list)
    status: str = "⏸️ 空闲"
    screenshot: Optional[bytes] = None
    agent: Optional[AgentWrapper] = None


class AppState:
    def __init__(self):
        self.settings = get_settings()
        self.adb_helper = ADBHelper(self.settings.adb_path or None)
        self.device_registry = DeviceRegistry()
        self.device_manager = DeviceManager(self.adb_helper, self.device_registry)
        self.file_transfer = FileTransferManager(self.adb_helper)
        self.knowledge_manager = KnowledgeManager()
        self.agent: Optional[AgentWrapper] = None
        self.current_screenshot: Optional[bytes] = None
        self.current_device: Optional[str] = self.settings.device_id
        if self.current_device:
            self.device_manager.set_current_device(self.current_device)
        self.is_task_running = False
        self.task_logs: List[str] = []
        # 缓存当前设备列表
        self._cached_devices: List[DeviceInfo] = []
        # 多设备任务状态
        self.device_states: Dict[str, DeviceTaskState] = defaultdict(DeviceTaskState)
        self.state_lock = threading.Lock()
        self.task_queue: List[dict] = []
        # AI 助手与调度
        self.assistant_planner = AssistantPlanner(
            api_base=self.settings.assistant_api_base,
            api_key=self.settings.assistant_api_key,
            model=self.settings.assistant_model,
        )
        self.scheduler: Optional[SchedulerManager] = None
        self.latest_plan: Optional[StructuredPlan] = None

    def add_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.task_logs.append(f"[{timestamp}] {message}")
        # 保留最近100条日志
        if len(self.task_logs) > 100:
            self.task_logs = self.task_logs[-100:]

    def add_device_log(self, device_id: str, message: str):
        timestamp = time.strftime("%H:%M:%S")
        with self.state_lock:
            state = self.device_states[device_id]
            state.logs.append(f"[{timestamp}] {message}")
            if len(state.logs) > 100:
                state.logs = state.logs[-100:]

    def reset_device_state(self, device_id: str):
        with self.state_lock:
            self.device_states[device_id] = DeviceTaskState()

    def set_device_status(self, device_id: str, status: str):
        with self.state_lock:
            state = self.device_states[device_id]
            state.status = status

    def set_device_screenshot(self, device_id: str, data: Optional[bytes]):
        with self.state_lock:
            state = self.device_states[device_id]
            state.screenshot = data

    def set_device_agent(self, device_id: str, agent: Optional[AgentWrapper]):
        with self.state_lock:
            state = self.device_states[device_id]
            state.agent = agent

    def refresh_assistant_planner(self):
        """同步助手配置"""
        self.assistant_planner.update_config(
            api_base=self.settings.assistant_api_base,
            api_key=self.settings.assistant_api_key,
            model=self.settings.assistant_model,
        )

    def get_device_logs(self, device_id: str) -> str:
        with self.state_lock:
            logs = self.device_states[device_id].logs
        return "\n".join(logs) if logs else "暂无日志"

    def snapshot_states(self) -> Dict[str, DeviceTaskState]:
        with self.state_lock:
            return {
                k: DeviceTaskState(
                    logs=list(v.logs),
                    status=v.status,
                    screenshot=v.screenshot,
                    agent=v.agent,
                )
                for k, v in self.device_states.items()
            }


app_state = AppState()


# ==================== 设备管理面板 ====================

def scan_devices():
    """扫描设备并更新下拉框"""
    devices = _ensure_cached_devices(force_refresh=True)

    if not devices:
        result_text = "未发现设备\n请确保:\n1. 手机已通过USB连接\n2. 已开启USB调试\n3. 已在手机上授权调试"
        return (
            result_text,
            gr.update(choices=[], value=None),
            gr.update(choices=[], value=[]),
            gr.update(choices=[], value=[]),
        )

    result_text = ""
    choices = []
    online_device_ids = []

    for d in devices:
        # 状态图标
        status_icon = "🟢" if d.is_online else "⚫"
        fav_icon = "⭐" if d.is_favorite else ""
        conn_icon = "📶" if d.is_remote else "🔌"

        result_text += f"{status_icon} {fav_icon}{d.display_name} ({d.device_id}) {conn_icon}\n"

        # 只添加在线设备到下拉框
        if d.is_online:
            choices.append(d.device_id)
            online_device_ids.append(d.device_id)

    # 如果没有在线设备，显示所有已保存设备
    if not choices:
        choices = [d.device_id for d in devices]

    multi_device_choices = [d.device_id for d in devices]
    selected = app_state.current_device if app_state.current_device in choices else None
    multi_selected = [app_state.current_device] if app_state.current_device in online_device_ids else []
    return (
        result_text.strip(),
        gr.update(choices=choices, value=selected),
        gr.update(choices=multi_device_choices, value=[]),
        gr.update(choices=multi_device_choices, value=multi_selected),
        gr.update(choices=multi_device_choices, value=[]),
        gr.update(choices=multi_device_choices, value=multi_selected),
    )


def select_device(device_id: str) -> Tuple[str, str, str, bool, Optional[Image.Image]]:
    """选择设备，返回 (设备信息, 自定义名称, 备注, 是否收藏, 截图)"""
    if not device_id:
        return "请先选择一个设备", "", "", False, None

    app_state.current_device = device_id
    app_state.device_manager.set_current_device(device_id)
    app_state.settings.device_id = device_id
    save_settings(app_state.settings)

    # 获取设备详细信息
    info = app_state.device_manager.get_device_display_info(device_id)

    status_icon = "🟢" if info.get("is_online") else "⚫"
    conn_type = "WiFi" if info.get("device_type") == "wifi" else "USB"

    info_text = f"""{status_icon} {info.get('status', '未知')} ({conn_type})
设备: {device_id}
品牌: {info.get('brand') or '未知'}
型号: {info.get('model') or '未知'}
Android: {info.get('android_version') or '未知'}"""

    # 同时刷新截图
    screenshot = None
    if info.get("is_online"):
        success, data = app_state.device_manager.take_screenshot(device_id)
        if success and data:
            app_state.current_screenshot = data
            screenshot = Image.open(io.BytesIO(data))

    return (
        info_text,
        info.get("custom_name", ""),
        info.get("notes", ""),
        info.get("is_favorite", False),
        screenshot
    )


def connect_wifi(ip_address: str):
    """WiFi连接设备"""
    if not ip_address:
        return "请输入IP地址"

    ip_address = ip_address.strip()
    if ":" not in ip_address:
        ip_address = f"{ip_address}:5555"

    ip, port = ip_address.rsplit(":", 1)
    success, message = app_state.device_manager.connect_remote(ip, int(port))

    if success:
        app_state.settings.last_wifi_address = ip_address
        save_settings(app_state.settings)
        return f"✅ {message}"
    return f"❌ {message}"


def disconnect_device() -> str:
    """断开设备连接"""
    success, message = app_state.device_manager.disconnect_all()
    app_state.current_device = None
    return "已断开所有远程连接"


# ==================== 设备编辑功能 ====================

def save_device_settings(custom_name: str, notes: str, is_favorite: bool) -> str:
    """保存设备自定义设置"""
    if not app_state.current_device:
        return "请先选择设备"

    device_id = app_state.current_device

    # 保存自定义名称
    app_state.device_manager.set_device_name(device_id, custom_name.strip())
    # 保存备注
    app_state.device_manager.set_device_notes(device_id, notes.strip())
    # 保存收藏状态
    app_state.device_manager.set_device_favorite(device_id, is_favorite)

    return f"✅ 设备设置已保存"


def delete_saved_device() -> str:
    """删除已保存的设备"""
    if not app_state.current_device:
        return "请先选择设备"

    device_id = app_state.current_device
    success = app_state.device_manager.remove_saved_device(device_id)

    if success:
        app_state.current_device = None
        return f"✅ 已删除设备记录: {device_id}"
    else:
        return "❌ 删除失败"


# ==================== 文件传输功能 ====================

def analyze_upload_files(files) -> str:
    """分析上传的文件"""
    if not files:
        return "请选择要上传的文件"

    file_infos = []
    for f in files:
        info = app_state.file_transfer.analyze_file(f.name)
        if info:
            file_infos.append(info)

    if not file_infos:
        return "无法识别的文件"

    result = f"已选择 {len(file_infos)} 个文件:\n\n"
    total_size = 0

    for info in file_infos:
        total_size += info.size
        type_icon = {
            FileType.APK: "📦",
            FileType.VIDEO: "🎬",
            FileType.AUDIO: "🎵",
            FileType.IMAGE: "🖼️",
            FileType.DOCUMENT: "📄",
            FileType.OTHER: "📁",
        }.get(info.file_type, "📁")

        result += f"{type_icon} {info.name} ({info.size_display})\n"
        result += f"   → {info.action_display}\n"

    # 总大小
    if total_size < 1024 * 1024:
        total_display = f"{total_size / 1024:.1f} KB"
    elif total_size < 1024 * 1024 * 1024:
        total_display = f"{total_size / (1024 * 1024):.1f} MB"
    else:
        total_display = f"{total_size / (1024 * 1024 * 1024):.2f} GB"

    result += f"\n总大小: {total_display}"

    return result


def _prepare_file_infos(files):
    """校验并解析上传文件"""
    if not files:
        return None, "❌ 请先选择文件"

    file_infos = app_state.file_transfer.analyze_files([f.name for f in files])
    if not file_infos:
        return None, "❌ 无法识别的文件"

    return file_infos, None


def _summarize_transfer_results(results, device_id: str):
    """汇总单设备传输结果"""
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count

    messages = []
    rows = []
    for res in results:
        icon = "✅" if res.success else "❌"
        messages.append(f"{icon} {res.file_info.name}: {res.message}")
        rows.append([
            device_id,
            res.file_info.name,
            f"{icon} {res.message}",
        ])

    summary = f"\n传输完成: {success_count} 成功, {fail_count} 失败\n\n" + "\n".join(messages)
    return summary, rows


def upload_files_to_devices(files, target_device_ids=None):
    """上传文件到单个或多个设备"""
    file_infos, error = _prepare_file_infos(files)
    if error:
        return error, []

    selected_devices = target_device_ids or []

    # 多设备传输
    if selected_devices:
        all_results = app_state.file_transfer.transfer_to_multiple_devices(
            file_infos,
            selected_devices,
        )
        summary_lines = []
        table_rows = []

        for device_id, results in all_results.items():
            success_count = sum(1 for r in results if r.success)
            fail_count = len(results) - success_count
            summary_lines.append(f"{device_id}: {success_count} 成功, {fail_count} 失败")

            for res in results:
                icon = "✅" if res.success else "❌"
                table_rows.append([
                    device_id,
                    res.file_info.name,
                    f"{icon} {res.message}",
                ])

        summary_text = "多设备传输完成:\n" + "\n".join(summary_lines)
        return summary_text, table_rows

    # 单设备回退
    if not app_state.current_device:
        return "❌ 请先选择设备", []

    single_results = app_state.file_transfer.transfer_files(
        file_infos,
        app_state.current_device,
    )
    summary, rows = _summarize_transfer_results(single_results, app_state.current_device)
    return summary, rows


def upload_files_to_device(files) -> str:
    """兼容旧逻辑的单设备上传"""
    summary, _ = upload_files_to_devices(files, None)
    return summary


def refresh_screenshot() -> Optional[Image.Image]:
    """刷新屏幕截图"""
    if not app_state.current_device:
        return None

    success, data = app_state.device_manager.take_screenshot(app_state.current_device)
    if success and data:
        app_state.current_screenshot = data
        return Image.open(io.BytesIO(data))
    return None


# ==================== 屏幕操作功能 ====================

# 存储屏幕尺寸用于坐标转换
_screen_size_cache = {}


def _get_screen_size() -> Tuple[int, int]:
    """获取当前设备屏幕尺寸"""
    if not app_state.current_device:
        return 1080, 1920
    if app_state.current_device not in _screen_size_cache:
        _screen_size_cache[app_state.current_device] = \
            app_state.device_manager.get_screen_size(app_state.current_device)
    return _screen_size_cache[app_state.current_device]


def handle_screen_click(evt: gr.SelectData) -> Tuple[str, Optional[Image.Image]]:
    """处理屏幕点击事件"""
    if not app_state.current_device:
        return "请先选择设备", None

    # 获取点击坐标（Gradio 返回的是图片上的坐标）
    x, y = evt.index

    # 获取实际屏幕尺寸进行坐标转换
    screen_w, screen_h = _get_screen_size()

    # 获取当前截图的实际显示尺寸
    if app_state.current_screenshot:
        img = Image.open(io.BytesIO(app_state.current_screenshot))
        img_w, img_h = img.size
        # 计算缩放比例
        scale_x = screen_w / img_w
        scale_y = screen_h / img_h
        # 转换坐标
        real_x = int(x * scale_x)
        real_y = int(y * scale_y)
    else:
        real_x, real_y = x, y

    # 执行点击
    success, msg = app_state.device_manager.tap(real_x, real_y, app_state.current_device)

    # 等待并刷新截图
    time.sleep(0.5)
    screenshot = refresh_screenshot()

    return f"✅ {msg}" if success else f"❌ {msg}", screenshot


def handle_swipe(direction: str) -> Tuple[str, Optional[Image.Image]]:
    """处理滑动操作"""
    if not app_state.current_device:
        return "请先选择设备", None

    screen_w, screen_h = _get_screen_size()
    cx, cy = screen_w // 2, screen_h // 2

    # 根据方向计算滑动坐标
    swipe_distance = min(screen_w, screen_h) // 3
    coords = {
        "up": (cx, cy + swipe_distance, cx, cy - swipe_distance),
        "down": (cx, cy - swipe_distance, cx, cy + swipe_distance),
        "left": (cx + swipe_distance, cy, cx - swipe_distance, cy),
        "right": (cx - swipe_distance, cy, cx + swipe_distance, cy),
    }

    if direction not in coords:
        return "无效的滑动方向", None

    x1, y1, x2, y2 = coords[direction]
    success, msg = app_state.device_manager.swipe(x1, y1, x2, y2, 300, app_state.current_device)

    time.sleep(0.5)
    screenshot = refresh_screenshot()
    return f"✅ {msg}" if success else f"❌ {msg}", screenshot


def handle_back() -> Tuple[str, Optional[Image.Image]]:
    """返回键"""
    if not app_state.current_device:
        return "请先选择设备", None
    success, msg = app_state.device_manager.press_back(app_state.current_device)
    time.sleep(0.3)
    screenshot = refresh_screenshot()
    return f"✅ 返回" if success else f"❌ {msg}", screenshot


def handle_home() -> Tuple[str, Optional[Image.Image]]:
    """主页键"""
    if not app_state.current_device:
        return "请先选择设备", None
    success, msg = app_state.device_manager.press_home(app_state.current_device)
    time.sleep(0.3)
    screenshot = refresh_screenshot()
    return f"✅ 主页" if success else f"❌ {msg}", screenshot


def handle_recent() -> Tuple[str, Optional[Image.Image]]:
    """最近任务"""
    if not app_state.current_device:
        return "请先选择设备", None
    success, msg = app_state.device_manager.press_recent(app_state.current_device)
    time.sleep(0.3)
    screenshot = refresh_screenshot()
    return f"✅ 最近任务" if success else f"❌ {msg}", screenshot


def handle_input_text(text: str) -> Tuple[str, Optional[Image.Image]]:
    """输入文本"""
    if not app_state.current_device:
        return "请先选择设备", None
    if not text:
        return "请输入文本", None

    success, msg = app_state.device_manager.input_text(text, app_state.current_device)
    time.sleep(0.3)
    screenshot = refresh_screenshot()
    return f"✅ {msg}" if success else f"❌ {msg}", screenshot


def handle_enter() -> Tuple[str, Optional[Image.Image]]:
    """回车键"""
    if not app_state.current_device:
        return "请先选择设备", None
    success, msg = app_state.device_manager.press_enter(app_state.current_device)
    time.sleep(0.3)
    screenshot = refresh_screenshot()
    return f"✅ 回车" if success else f"❌ {msg}", screenshot


# ADB键盘下载地址
ADB_KEYBOARD_URL = "https://github.com/nicksay/ADBKeyboard/releases/download/v1.0/ADBKeyboard.apk"


def handle_install_adb_keyboard() -> str:
    """安装ADB键盘"""
    if not app_state.current_device:
        return "请先选择设备"

    # 先检查是否已安装
    success, output = app_state.device_manager.run_shell_command(
        "pm list packages com.android.adbkeyboard",
        app_state.current_device
    )
    if success and "com.android.adbkeyboard" in output:
        return "✅ ADB键盘已安装，无需重复安装"

    return "⏳ 请手动下载 ADB Keyboard APK 并安装:\n" + ADB_KEYBOARD_URL


def handle_enable_adb_keyboard() -> str:
    """启用ADB键盘"""
    if not app_state.current_device:
        return "请先选择设备"

    success, msg = app_state.device_manager.enable_adb_keyboard(app_state.current_device)
    return f"✅ {msg}" if success else f"❌ {msg}"


def handle_open_ime_settings() -> Tuple[str, Optional[Image.Image]]:
    """打开输入法设置"""
    if not app_state.current_device:
        return "请先选择设备", None

    success, msg = app_state.device_manager.open_language_settings(app_state.current_device)
    time.sleep(0.5)
    screenshot = refresh_screenshot()
    return f"✅ {msg}" if success else f"❌ {msg}", screenshot


def handle_open_settings() -> Tuple[str, Optional[Image.Image]]:
    """打开系统设置"""
    if not app_state.current_device:
        return "请先选择设备", None

    success, msg = app_state.device_manager.open_settings(app_state.current_device)
    time.sleep(0.5)
    screenshot = refresh_screenshot()
    return f"✅ {msg}" if success else f"❌ {msg}", screenshot


def handle_list_ime() -> str:
    """列出输入法"""
    if not app_state.current_device:
        return "请先选择设备"

    success, output = app_state.device_manager.list_ime(app_state.current_device)
    if success:
        return f"已安装的输入法:\n{output}"
    return f"❌ 获取失败: {output}"


def handle_custom_command(command: str) -> str:
    """执行自定义ADB命令"""
    if not app_state.current_device:
        return "请先选择设备"
    if not command:
        return "请输入命令"

    # 安全检查：禁止危险命令
    dangerous = ["rm -rf", "format", "factory", "wipe"]
    for d in dangerous:
        if d in command.lower():
            return f"❌ 禁止执行危险命令: {d}"

    success, output = app_state.device_manager.run_adb_command(command, app_state.current_device)
    return f"{'✅' if success else '❌'} 执行结果:\n{output}"


def handle_clear_cache() -> str:
    """清理Gradio缓存"""
    success = clear_gradio_cache()
    if success:
        return "✅ 缓存已清理"
    return "❌ 清理缓存失败"


def handle_install_apk(file) -> str:
    """安装APK文件"""
    if not app_state.current_device:
        return "请先选择设备"
    if file is None:
        return "请选择APK文件"

    success, msg = app_state.device_manager.install_apk(file.name, app_state.current_device)
    return f"✅ {msg}" if success else f"❌ {msg}"


# ==================== 知识库管理面板 ====================

def get_knowledge_list_and_choices():
    """获取知识库列表和下拉选项"""
    items = app_state.knowledge_manager.get_all()

    if not items:
        list_text = "知识库为空，点击「创建默认模板」添加示例"
        choices = []
    else:
        list_text = ""
        for item in items:
            keywords = ", ".join(item.keywords[:3])
            if len(item.keywords) > 3:
                keywords += "..."
            list_text += f"📄 **{item.title}** (ID: {item.id})\n"
            list_text += f"   触发词: {keywords}\n\n"
        choices = [item.id for item in items]

    return list_text, gr.update(choices=choices, value=None)


def load_knowledge_item(item_id: str) -> Tuple[str, str, str, str]:
    """加载知识条目到编辑区"""
    if not item_id:
        return "", "", "", ""

    item = app_state.knowledge_manager.get(item_id)
    if not item:
        return "", "", "", ""

    return item.id, item.title, ", ".join(item.keywords), item.content


def save_knowledge_item(item_id: str, title: str, keywords: str, content: str):
    """保存知识条目"""
    if not title or not content:
        return "标题和内容不能为空", gr.update(), gr.update()

    # 解析关键词
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        return "请至少添加一个触发词", gr.update(), gr.update()

    if item_id:
        # 更新现有条目
        item = app_state.knowledge_manager.update(
            item_id, title=title, keywords=keyword_list, content=content
        )
        if item:
            status = f"已更新: {title}"
        else:
            status = "更新失败，条目不存在"
    else:
        # 创建新条目
        item = app_state.knowledge_manager.create(
            title=title, keywords=keyword_list, content=content
        )
        status = f"已创建: {title} (ID: {item.id})"

    # 刷新列表
    list_text, dropdown_update = get_knowledge_list_and_choices()
    return status, list_text, dropdown_update


def create_new_knowledge() -> Tuple[str, str, str, str]:
    """新建知识条目"""
    return "", "", "", ""


def delete_knowledge_item(item_id: str):
    """删除知识条目"""
    if not item_id:
        return "请先选择要删除的条目", gr.update(), gr.update()

    success = app_state.knowledge_manager.delete(item_id)
    if success:
        status = "删除成功"
    else:
        status = "删除失败，条目不存在"

    # 刷新列表
    list_text, dropdown_update = get_knowledge_list_and_choices()
    return status, list_text, dropdown_update


def create_default_templates():
    """创建默认模板"""
    app_state.knowledge_manager.create_default_templates()
    list_text, dropdown_update = get_knowledge_list_and_choices()
    return "已创建默认模板", list_text, dropdown_update


def export_knowledge(filepath: str) -> str:
    """导出知识库"""
    if not filepath:
        filepath = "knowledge_export.json"
    try:
        app_state.knowledge_manager.export_to_file(filepath)
        return f"已导出到: {filepath}"
    except Exception as e:
        return f"导出失败: {str(e)}"


def import_knowledge(file):
    """导入知识库"""
    if file is None:
        return "请选择文件", gr.update(), gr.update()
    try:
        count = app_state.knowledge_manager.import_from_file(file.name)
        list_text, dropdown_update = get_knowledge_list_and_choices()
        return f"成功导入 {count} 条知识", list_text, dropdown_update
    except Exception as e:
        return f"导入失败: {str(e)}", gr.update(), gr.update()


# ==================== 任务执行面板 ====================

def _ensure_cached_devices(force_refresh: bool = False) -> List[DeviceInfo]:
    if force_refresh or not app_state._cached_devices:
        app_state._cached_devices = app_state.device_manager.scan_devices()
    return app_state._cached_devices


def _resolve_target_devices(target_device_ids: List[str]) -> Tuple[List[str], Optional[str]]:
    devices = _ensure_cached_devices(force_refresh=True)
    online_map = {d.device_id: d.is_online for d in devices}
    default_targets = target_device_ids or ([] if not app_state.current_device else [app_state.current_device])

    if not default_targets:
        default_targets = [d.device_id for d in devices if d.is_online]

    available_devices = [d for d in default_targets if online_map.get(d)]
    offline_selected = [d for d in default_targets if d not in online_map or not online_map[d]]

    if not available_devices:
        return [], "请至少选择一个在线设备"

    warning = None
    if offline_selected:
        warning = f"已忽略离线设备: {', '.join(offline_selected)}"

    return available_devices, warning


def prepare_task_queue(task: str, use_knowledge: bool, device_ids: List[str]) -> Tuple[bool, str, List[str]]:
    """准备任务并放入队列"""
    if not task:
        return False, "请输入任务描述", []

    available_devices, warning = _resolve_target_devices(device_ids)
    if not available_devices:
        return False, "请至少选择一个在线设备", []

    with app_state.state_lock:
        app_state.task_queue = [{
            "task": task,
            "use_knowledge": use_knowledge,
            "device_ids": available_devices,
        }]

    for device_id in available_devices:
        app_state.reset_device_state(device_id)
        app_state.set_device_status(device_id, "⏳ 排队中")

    return True, warning or "任务已加入队列", available_devices


def execute_task_for_device(task: str, use_knowledge: bool, device_id: str) -> Optional[TaskResult]:
    """在单个设备上执行任务"""
    settings = app_state.settings
    agent = AgentWrapper(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
        model_name=settings.model_name,
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        device_id=device_id,
        device_type=settings.device_type,
        max_steps=settings.max_steps,
        language=settings.language,
        verbose=settings.verbose,
        knowledge_manager=app_state.knowledge_manager if use_knowledge else None,
        use_knowledge_base=use_knowledge,
    )

    agent.on_log_callback = lambda msg, did=device_id: app_state.add_device_log(did, msg)
    app_state.set_device_agent(device_id, agent)
    app_state.set_device_status(device_id, "🚀 执行中")

    task_gen = agent.run_task(task)
    task_result: Optional[TaskResult] = None

    try:
        while True:
            step_result = next(task_gen)
            if step_result.screenshot:
                app_state.set_device_screenshot(device_id, step_result.screenshot)
            status_text = "✅ 任务完成" if step_result.finished else "🚀 执行中"
            app_state.set_device_status(device_id, status_text)
    except StopIteration as stop:
        task_result = stop.value
        if task_result and not task_result.success:
            app_state.set_device_status(device_id, f"❌ {task_result.message}")
        else:
            app_state.set_device_status(device_id, "✅ 任务完成")
    except Exception as e:
        app_state.add_device_log(device_id, f"任务执行错误: {str(e)}")
        app_state.set_device_status(device_id, f"❌ {e}")
    finally:
        app_state.set_device_agent(device_id, None)

    return task_result


def start_task_execution(parallel: bool = True):
    """启动队列中的任务"""
    with app_state.state_lock:
        if app_state.is_task_running:
            return False, "已有任务在执行中", None
        if not getattr(app_state, "task_queue", []):
            return False, "任务队列为空", None
        job = app_state.task_queue.pop(0)
        app_state.is_task_running = True

    results: Dict[str, Optional[TaskResult]] = {}
    threads: List[threading.Thread] = []

    def worker(device_id: str):
        results[device_id] = execute_task_for_device(job["task"], job["use_knowledge"], device_id)

    if parallel:
        for device_id in job["device_ids"]:
            t = threading.Thread(target=worker, args=(device_id,), daemon=True)
            threads.append(t)
            t.start()
    else:
        for device_id in job["device_ids"]:
            worker(device_id)

    if not threads:
        app_state.is_task_running = False

    return True, "任务已启动", {"threads": threads, "results": results, "devices": job["device_ids"]}


def _wait_for_task_threads(threads: Optional[List[threading.Thread]]):
    """等待任务线程结束"""
    if not threads:
        return
    for t in threads:
        t.join()


def _collect_execution_outcome(
    results: Dict[str, Optional[TaskResult]],
    devices: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """根据执行结果汇总最终状态，并重置运行标记"""
    target_devices = devices or list(results.keys())
    failures = []

    for device_id in target_devices:
        res = results.get(device_id)
        if res is None or (res and not res.success):
            failures.append(device_id)

    for device_id, state in app_state.snapshot_states().items():
        if device_id in target_devices and state.status.startswith("❌") and device_id not in failures:
            failures.append(device_id)

    app_state.is_task_running = False
    success = not failures
    final_status = "✅ 所有设备完成" if success else f"❌ 部分设备失败: {', '.join(failures)}"
    return success, final_status


def _render_device_status_board() -> str:
    states = app_state.snapshot_states()
    if not states:
        return "暂无设备状态"

    lines = []
    for device_id, state in states.items():
        if not state.logs and state.status == "⏸️ 空闲" and not state.screenshot:
            continue
        lines.append(f"- **{device_id}**: {state.status}")
    if not lines:
        return "暂无设备状态"
    return "\n".join(lines)


def _render_device_logs() -> str:
    states = app_state.snapshot_states()
    if not states:
        return "暂无日志"

    sections = []
    for device_id, state in states.items():
        if not state.logs:
            continue
        logs = state.logs[-20:] if state.logs else ["暂无日志"]
        sections.append(f"#### {device_id}\n```\n" + "\n".join(logs) + "\n```")
    if not sections:
        return "暂无日志"
    return "\n\n".join(sections)


def _render_screenshot_gallery():
    states = app_state.snapshot_states()
    gallery_items = []
    for device_id, state in states.items():
        if state.screenshot:
            try:
                img = Image.open(io.BytesIO(state.screenshot))
                gallery_items.append((img, f"{device_id}"))
            except Exception:
                continue
    return gallery_items


def query_task_status():
    """查询当前任务状态"""
    return _render_device_status_board(), _render_device_logs(), _render_screenshot_gallery()


def run_task(task: str, use_knowledge: bool, device_ids: List[str]):
    """执行任务，实时返回状态/截图/日志"""
    if app_state.is_task_running:
        yield "已有任务在执行中", _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()
        return

    device_ids = device_ids or []
    success, message, target_devices = prepare_task_queue(task, use_knowledge, device_ids)
    if not success:
        yield message, _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()
        return

    start_ok, start_message, context = start_task_execution(parallel=True)
    if not start_ok or context is None:
        yield start_message, _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()
        return

    status_hint = start_message if start_message else "🔄 任务执行中..."
    if message and message != start_message:
        status_hint = f"{status_hint} ({message})"

    threads = context.get("threads", [])
    results = context.get("results", {})
    devices = context.get("devices", target_devices)

    yield f"{status_hint} | 目标设备: {', '.join(devices)}", _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()

    while threads and any(t.is_alive() for t in threads):
        time.sleep(0.5)
        yield "🔄 任务执行中...", _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()

    _wait_for_task_threads(threads)
    _, final_status = _collect_execution_outcome(results, devices)
    yield final_status, _render_screenshot_gallery(), _render_device_logs(), _render_device_status_board()


def stop_task() -> str:
    """停止任务"""
    stopped_devices = []
    for device_id, state in app_state.snapshot_states().items():
        if state.agent and state.agent.is_running():
            state.agent.stop()
            stopped_devices.append(device_id)
    if app_state.agent and getattr(app_state.agent, "is_running", lambda: False)():
        app_state.agent.stop()
        stopped_devices.append("current")
    if stopped_devices:
        for device_id in stopped_devices:
            if device_id != "current":
                app_state.set_device_status(device_id, "⏹️ 手动停止")
        app_state.is_task_running = False
        return "正在停止所有任务..."
    return "没有正在执行的任务"


def get_task_logs() -> str:
    """获取任务日志"""
    return _render_device_logs()


def get_task_screenshot():
    """获取任务截图"""
    return _render_screenshot_gallery()


def get_task_status() -> str:
    """获取任务状态"""
    if app_state.is_task_running:
        return "🔄 任务执行中..."
    return "⏸️ 空闲"


# ==================== AI 助手与调度 ====================

def _ensure_scheduler() -> SchedulerManager:
    if app_state.scheduler:
        return app_state.scheduler

    def _task_executor(job: JobSpec):
        success, warning, target_devices = prepare_task_queue(
            job.description, job.use_knowledge, job.device_ids
        )
        if not success:
            return False, warning

        start_ok, start_message, context = start_task_execution(parallel=job.parallel)
        if not start_ok or context is None:
            if start_ok and app_state.is_task_running:
                app_state.is_task_running = False
            return False, start_message or "任务启动失败"

        _wait_for_task_threads(context.get("threads"))
        success, final_status = _collect_execution_outcome(
            context.get("results", {}), context.get("devices", target_devices)
        )

        status_parts = [start_message or ""]
        if warning and warning != start_message:
            status_parts.append(warning)
        status_prefix = " | ".join([p for p in status_parts if p])
        if status_prefix:
            final_status = f"{status_prefix} → {final_status}"
        return success, final_status

    app_state.scheduler = SchedulerManager(task_executor=_task_executor)
    return app_state.scheduler


def _build_device_context_message() -> str:
    """构造设备上下文，传递给助手提示可用设备"""
    devices = _ensure_cached_devices(force_refresh=True)
    if not devices:
        return "设备状态：当前未发现任何可用设备，请在生成计划时提醒用户先连接设备。"

    online = [
        f"{d.full_display_name}"
        for d in devices
        if d.is_online
    ]
    offline = [
        f"{d.full_display_name}（{d.status_text}）"
        for d in devices
        if not d.is_online
    ]

    online_text = ", ".join(online) if online else "无在线设备"
    offline_text = ", ".join(offline) if offline else "无离线设备"
    return (
        "当前设备状态（系统自动提供）："
        f"在线设备: {online_text}；离线/未授权: {offline_text}。"
        "请优先选择在线设备 ID 安排任务。"
    )


def reset_assistant_session():
    """重置助手会话"""
    app_state.assistant_planner.start_session()
    app_state.latest_plan = None
    return [], "✅ 新会话已开始"


def assistant_chat(user_msg: str, chat_history: List[Any]):
    """助手对话，返回 (更新后的历史, 清空的输入框)"""
    if not user_msg or not user_msg.strip():
        return chat_history or [], ""

    device_context = _build_device_context_message()
    reply = app_state.assistant_planner.chat(
        user_msg,
        context_messages=[{"role": "system", "content": device_context}],
    )

    # 使用 messages 格式（Gradio 4.44+ 默认格式）
    new_messages = [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]
    history = (chat_history or []) + new_messages
    return history, ""  # 返回空字符串清空输入框


def _format_structured_plan(plan: StructuredPlan) -> str:
    rows = [
        "| 字段 | 内容 |",
        "| --- | --- |",
        f"| 任务描述 | {plan.task_description} |",
        f"| 目标设备 | {', '.join(plan.target_devices) if plan.target_devices else '未指定'} |",
        f"| 时间要求 | {plan.time_requirement or '未指定'} |",
        f"| 频率 | {plan.frequency or '一次性'} |",
    ]
    return "\n".join(rows)


def generate_structured_plan(devices: List[str], time_requirement: str):
    """生成结构化计划"""
    device_context = _build_device_context_message()
    preferred_devices = devices or [d.device_id for d in _ensure_cached_devices(force_refresh=True) if d.is_online]
    plan = app_state.assistant_planner.summarize_plan(
        preferred_devices,
        time_requirement,
        context_messages=[{"role": "system", "content": device_context}],
    )
    app_state.latest_plan = plan
    return _format_structured_plan(plan), plan.to_dict()


def _build_rule(rule_type: str, run_at: str, interval_minutes: float, daily_time: str) -> Dict:
    rule_type = (rule_type or "").lower()
    if rule_type == "once":
        return {"type": "once", "run_at": run_at or datetime.now().isoformat()}
    if rule_type == "daily":
        return {"type": "daily", "time": daily_time or "09:00"}
    # default interval
    minutes = interval_minutes or 0
    return {"type": "interval", "minutes": minutes if minutes > 0 else 60}


def _describe_rule(rule: Dict[str, str]) -> str:
    rtype = (rule.get("type") or "").lower()
    if rtype == "once":
        return f"一次性@{rule.get('run_at', '-')}"
    if rtype == "daily":
        return f"每日@{rule.get('time', '09:00')}"
    if rtype == "interval":
        minutes = rule.get("minutes")
        seconds = rule.get("seconds")
        val = minutes if minutes else (seconds / 60 if seconds else 60)
        return f"间隔 {val} 分钟"
    return "未设置"


def _render_jobs_markdown() -> str:
    scheduler = _ensure_scheduler()
    jobs = scheduler.list_jobs()
    if not jobs:
        return "暂无定时任务"

    header = "| ID | 描述 | 设备 | 规则 | 启用 | 下次执行 | 最近状态 |\n| --- | --- | --- | --- | --- | --- | --- |"
    rows = []
    for job in jobs:
        rows.append(
            f"| {job.id} | {job.description} | {', '.join(job.device_ids) or '-'} | "
            f"{_describe_rule(job.rule)} | {'✅' if job.enabled else '⏸️'} | "
            f"{job.next_run or '-'} | {job.last_status or '-'} |"
        )
    return "\n".join([header] + rows)


def add_scheduled_job(
    description: str,
    device_ids: List[str],
    use_kb: bool,
    rule_type: str,
    run_at: str,
    interval_minutes: float,
    daily_time: str,
    parallel: bool = True,
):
    scheduler = _ensure_scheduler()
    rule = _build_rule(rule_type, run_at, interval_minutes, daily_time)
    job = scheduler.add_job(
        {
            "description": description or "未命名任务",
            "device_ids": device_ids or [],
            "use_knowledge": use_kb,
            "rule": rule,
            "parallel": parallel,
        }
    )
    return f"✅ 已创建任务 {job.id}", _render_jobs_markdown()


def remove_scheduled_job(job_id: str):
    scheduler = _ensure_scheduler()
    if not job_id:
        return "请输入要删除的任务ID", _render_jobs_markdown()
    ok = scheduler.remove_job(job_id)
    status = "✅ 已删除" if ok else "未找到任务"
    return status, _render_jobs_markdown()


def toggle_scheduled_job(job_id: str, enabled: bool):
    scheduler = _ensure_scheduler()
    if not job_id:
        return "请输入任务ID", _render_jobs_markdown()
    ok = scheduler.toggle_job(job_id, enabled)
    status = "✅ 已更新" if ok else "未找到任务"
    return status, _render_jobs_markdown()


def refresh_scheduled_jobs():
    return _render_jobs_markdown()


def enable_scheduled_job(job_id: str):
    return toggle_scheduled_job(job_id, True)


def disable_scheduled_job(job_id: str):
    return toggle_scheduled_job(job_id, False)


def execute_plan_now(plan_data: Dict, use_knowledge: bool, parallel: bool):
    plan = plan_data or (app_state.latest_plan.to_dict() if app_state.latest_plan else {})
    task_desc = plan.get("task_description") or plan.get("description") or ""
    device_ids = plan.get("target_devices") or []
    if not task_desc:
        return "请先生成计划"
    success, message, targets = prepare_task_queue(task_desc, use_knowledge, device_ids)
    if not success:
        return message
    start_ok, start_message, _ = start_task_execution(parallel=parallel)
    if not start_ok:
        return start_message
    return start_message or "任务已启动"


def import_plan_to_scheduler(
    plan_data: Dict,
    rule_type: str,
    run_at: str,
    interval_minutes: float,
    daily_time: str,
    use_knowledge: bool,
    parallel: bool,
):
    plan = plan_data or (app_state.latest_plan.to_dict() if app_state.latest_plan else {})
    if not plan:
        return "请先生成计划", _render_jobs_markdown()
    description = plan.get("task_description") or "未命名任务"
    device_ids = plan.get("target_devices") or []
    return add_scheduled_job(
        description=description,
        device_ids=device_ids,
        use_kb=use_knowledge,
        rule_type=rule_type,
        run_at=run_at,
        interval_minutes=interval_minutes,
        daily_time=daily_time,
        parallel=parallel,
    )


def refresh_task_panels():
    """同时刷新日志和状态面板"""
    return _render_device_logs(), _render_device_status_board()


# ==================== 设置面板 ====================

def load_settings() -> Tuple[str, str, str, int, float, int, float, str, bool, str, str, str]:
    """加载设置"""
    s = app_state.settings
    return (
        s.api_base_url,
        s.api_key,
        s.model_name,
        s.max_tokens,
        s.temperature,
        s.max_steps,
        s.action_delay,
        s.language,
        s.verbose,
        s.assistant_api_base,
        s.assistant_api_key,
        s.assistant_model,
    )


def save_settings_form(
    api_base_url: str,
    api_key: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    max_steps: int,
    action_delay: float,
    language: str,
    verbose: bool,
    assistant_api_base: str,
    assistant_api_key: str,
    assistant_model: str,
) -> str:
    """保存设置"""
    app_state.settings.api_base_url = api_base_url
    app_state.settings.api_key = api_key
    app_state.settings.model_name = model_name
    app_state.settings.max_tokens = max_tokens
    app_state.settings.temperature = temperature
    app_state.settings.max_steps = max_steps
    app_state.settings.action_delay = action_delay
    app_state.settings.language = language
    app_state.settings.verbose = verbose
    app_state.settings.assistant_api_base = assistant_api_base
    app_state.settings.assistant_api_key = assistant_api_key
    app_state.settings.assistant_model = assistant_model

    app_state.refresh_assistant_planner()
    save_settings(app_state.settings)
    return "设置已保存"


def test_api() -> str:
    """测试API连接"""
    settings = app_state.settings
    agent = AgentWrapper(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
        model_name=settings.model_name,
        device_type=settings.device_type,
    )
    success, message = agent.test_api_connection()
    return f"{'✅' if success else '❌'} {message}"


def check_adb_status() -> str:
    """检查ADB状态"""
    if app_state.adb_helper.is_available():
        version = app_state.adb_helper.get_version()
        return f"✅ ADB可用\n{version}"
    return "❌ ADB不可用，请确保ADB工具已正确配置"


# ==================== 创建应用 ====================

def create_app() -> gr.Blocks:
    """创建Gradio应用"""

    with gr.Blocks(
        title="Phone Agent - AI手机助手",
    ) as app:
        gr.Markdown(
            """
            # 📱 Phone Agent - AI手机助手
            通过自然语言控制您的Android手机，支持知识库增强
            """
        )

        with gr.Tabs():
            # ============ 设备管理 Tab ============
            with gr.Tab("📱 设备管理"):
                with gr.Row():
                    # ===== 左侧：设备连接 =====
                    with gr.Column(scale=1):
                        # 设备扫描与选择
                        with gr.Group():
                            gr.Markdown("### 📱 设备连接")
                            with gr.Row():
                                scan_btn = gr.Button("🔍 扫描设备", variant="primary", scale=2)
                                disconnect_btn = gr.Button("断开全部", scale=1)
                            device_list = gr.Textbox(
                                label="设备列表",
                                lines=3,
                                interactive=False,
                            )
                            device_dropdown = gr.Dropdown(
                                label="选择设备",
                                choices=[],
                                interactive=True,
                                allow_custom_value=True,
                                value=app_state.current_device,
                            )
                            device_info = gr.Textbox(
                                label="设备信息",
                                lines=5,
                                interactive=False,
                            )

                        # WiFi连接
                        with gr.Group():
                            gr.Markdown("### 📶 WiFi连接")
                            with gr.Row():
                                wifi_ip = gr.Textbox(
                                    label="",
                                    placeholder="IP:端口 (如 192.168.1.100:5555)",
                                    value=app_state.settings.last_wifi_address,
                                    scale=3,
                                )
                                connect_btn = gr.Button("连接", scale=1)
                            wifi_status = gr.Textbox(
                                label="",
                                interactive=False,
                                lines=1,
                            )

                        # 设备设置（折叠）
                        with gr.Accordion("⚙️ 设备设置", open=False):
                            device_custom_name = gr.Textbox(
                                label="自定义名称",
                                placeholder="例如: 测试机A",
                            )
                            device_notes = gr.Textbox(
                                label="备注",
                                placeholder="设备用途说明...",
                                lines=2,
                            )
                            device_favorite = gr.Checkbox(label="⭐ 收藏此设备", value=False)
                            with gr.Row():
                                save_device_btn = gr.Button("💾 保存", variant="primary")
                                delete_device_btn = gr.Button("🗑️ 删除记录", variant="stop")
                            device_edit_status = gr.Textbox(label="", interactive=False, lines=1)

                        # 文件传输（折叠）
                        with gr.Accordion("📁 文件传输", open=False):
                            upload_files = gr.File(
                                label="选择文件 (支持多选: APK/视频/音频/图片/文档)",
                                file_count="multiple",
                                file_types=[
                                    ".apk", ".xapk",
                                    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".3gp",
                                    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a",
                                    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
                                    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt",
                                    ".zip", ".rar", ".7z"
                                ],
                            )
                            multi_device_selector = gr.CheckboxGroup(
                                label="选择多个设备",
                                choices=[],
                                interactive=True,
                                info="勾选后同时推送到所选设备；留空则使用当前设备",
                            )
                            upload_file_info = gr.Textbox(label="文件信息", interactive=False, lines=3)
                            upload_btn = gr.Button("📤 上传到设备", variant="primary")
                            upload_status = gr.Textbox(label="传输结果", interactive=False, lines=3)
                            upload_result_table = gr.Dataframe(
                                headers=["设备ID", "文件名", "结果"],
                                label="详细结果",
                                interactive=False,
                                row_count=(0, "dynamic"),
                                column_count=(3, "fixed"),
                            )

                    # ===== 右侧：屏幕操作 =====
                    with gr.Column(scale=2):
                        gr.Markdown("### 🖥️ 屏幕操作")
                        preview_image = gr.Image(
                            label="点击屏幕直接操作",
                            type="pil",
                            height=480,
                            interactive=True,
                        )
                        operation_status = gr.Textbox(label="", interactive=False, lines=1)

                        # 导航按钮
                        with gr.Row():
                            refresh_btn = gr.Button("🔄 刷新")
                            back_btn = gr.Button("◀ 返回")
                            home_btn = gr.Button("🏠 主页")
                            recent_btn = gr.Button("📋 最近")

                        # 滑动按钮
                        with gr.Row():
                            swipe_up_btn = gr.Button("⬆ 上滑")
                            swipe_down_btn = gr.Button("⬇ 下滑")
                            swipe_left_btn = gr.Button("⬅ 左滑")
                            swipe_right_btn = gr.Button("➡ 右滑")

                        # 文本输入
                        with gr.Row():
                            text_input = gr.Textbox(label="", placeholder="输入文本...", scale=4)
                            send_text_btn = gr.Button("发送", scale=1)
                            enter_btn = gr.Button("回车", scale=1)

                        # 快捷工具（折叠）
                        with gr.Accordion("🔧 快捷工具", open=False):
                            with gr.Row():
                                with gr.Column():
                                    gr.Markdown("**ADB键盘 (中文输入)**")
                                    install_adb_kb_btn = gr.Button("📥 检查/安装")
                                    enable_adb_kb_btn = gr.Button("✅ 启用")
                                    open_ime_btn = gr.Button("⚙️ 输入法设置")
                                    list_ime_btn = gr.Button("📋 查看输入法")
                                with gr.Column():
                                    gr.Markdown("**系统工具**")
                                    open_settings_btn = gr.Button("⚙️ 系统设置")
                                    clear_cache_btn = gr.Button("🧹 清理缓存")
                                    gr.Markdown("**自定义命令**")
                                    custom_cmd = gr.Textbox(label="", placeholder="shell dumpsys activity")
                                    run_cmd_btn = gr.Button("▶ 执行")
                            tool_status = gr.Textbox(label="工具状态", interactive=False, lines=3)
                            cmd_output = gr.Textbox(label="命令输出", interactive=False, lines=3)

            # ============ 知识库管理 Tab ============
            with gr.Tab("📚 知识库"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 知识库列表")
                        knowledge_list_display = gr.Markdown("加载中...")
                        refresh_kb_btn = gr.Button("🔄 刷新列表")

                        gr.Markdown("### 操作")
                        knowledge_dropdown = gr.Dropdown(
                            label="选择条目编辑",
                            choices=[],
                            interactive=True,
                            allow_custom_value=True,
                        )
                        with gr.Row():
                            new_kb_btn = gr.Button("➕ 新建")
                            delete_kb_btn = gr.Button("🗑️ 删除", variant="stop")

                        gr.Markdown("### 导入/导出")
                        with gr.Row():
                            export_btn = gr.Button("📤 导出")
                            import_file = gr.File(label="导入文件", file_types=[".json"])
                        import_export_status = gr.Textbox(label="状态", interactive=False)

                        create_template_btn = gr.Button("📝 创建默认模板")

                    with gr.Column(scale=2):
                        gr.Markdown("### 编辑区")
                        kb_id = gr.Textbox(label="ID (自动生成)", interactive=False, visible=False)
                        kb_title = gr.Textbox(label="标题", placeholder="例如: 淘宝购物流程")
                        kb_keywords = gr.Textbox(
                            label="触发词 (逗号分隔)",
                            placeholder="淘宝, 购物, 买东西",
                        )
                        kb_content = gr.Textbox(
                            label="内容",
                            placeholder="详细的操作步骤说明...",
                            lines=15,
                        )
                        save_kb_btn = gr.Button("💾 保存", variant="primary")
                        save_status = gr.Textbox(label="保存状态", interactive=False)

                # 事件绑定
                refresh_kb_btn.click(
                    fn=get_knowledge_list_and_choices,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

                knowledge_dropdown.change(
                    fn=load_knowledge_item,
                    inputs=[knowledge_dropdown],
                    outputs=[kb_id, kb_title, kb_keywords, kb_content],
                )

                new_kb_btn.click(
                    fn=create_new_knowledge,
                    outputs=[kb_id, kb_title, kb_keywords, kb_content],
                )

                save_kb_btn.click(
                    fn=save_knowledge_item,
                    inputs=[kb_id, kb_title, kb_keywords, kb_content],
                    outputs=[save_status, knowledge_list_display, knowledge_dropdown],
                )

                delete_kb_btn.click(
                    fn=delete_knowledge_item,
                    inputs=[kb_id],
                    outputs=[save_status, knowledge_list_display, knowledge_dropdown],
                ).then(
                    fn=create_new_knowledge,
                    outputs=[kb_id, kb_title, kb_keywords, kb_content],
                )

                create_template_btn.click(
                    fn=create_default_templates,
                    outputs=[import_export_status, knowledge_list_display, knowledge_dropdown],
                )

                export_btn.click(
                    fn=lambda: export_knowledge("knowledge_export.json"),
                    outputs=[import_export_status],
                )

                import_file.change(
                    fn=import_knowledge,
                    inputs=[import_file],
                    outputs=[import_export_status, knowledge_list_display, knowledge_dropdown],
                )

                # 初始加载
                app.load(
                    fn=get_knowledge_list_and_choices,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

            # ============ 任务执行 Tab ============
            with gr.Tab("🚀 任务执行"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 任务输入")
                        task_input = gr.Textbox(
                            label="任务描述",
                            placeholder="例如: 打开淘宝搜索无线耳机，找一个100元以内的",
                            lines=3,
                        )
                        use_kb_checkbox = gr.Checkbox(
                            label="启用知识库辅助",
                            value=True,
                        )
                        task_device_selector = gr.CheckboxGroup(
                            label="执行设备",
                            choices=[],
                            info="不选择时默认当前在线设备；仅会对在线设备执行任务",
                        )
                        with gr.Row():
                            run_btn = gr.Button("▶️ 开始执行", variant="primary", scale=2)
                            stop_btn = gr.Button("⏹️ 停止", variant="stop", scale=1)

                        task_status = gr.Textbox(
                            label="状态",
                            value="⏸️ 空闲",
                            interactive=False,
                        )

                        with gr.Accordion("📟 设备状态", open=True):
                            device_status_board = gr.Markdown("暂无设备状态")

                        with gr.Accordion("📜 执行日志", open=True):
                            log_area = gr.Markdown("暂无日志")
                            refresh_log_btn = gr.Button("🔄 刷新日志")

                    with gr.Column(scale=1):
                        gr.Markdown("### 实时屏幕")
                        task_screenshot = gr.Gallery(
                            label="",
                            columns=2,
                            height=500,
                            object_fit="contain",
                        )
                        refresh_task_screenshot_btn = gr.Button("🔄 刷新截图")

                # 事件绑定
                run_btn.click(
                    fn=run_task,
                    inputs=[task_input, use_kb_checkbox, task_device_selector],
                    outputs=[task_status, task_screenshot, log_area, device_status_board],
                )

                stop_btn.click(
                    fn=stop_task,
                    outputs=[task_status],
                ).then(
                    fn=refresh_task_panels,
                    outputs=[log_area, device_status_board],
                )

                refresh_log_btn.click(
                    fn=refresh_task_panels,
                    outputs=[log_area, device_status_board],
                )

                refresh_task_screenshot_btn.click(
                    fn=get_task_screenshot,
                    outputs=[task_screenshot],
                )

            # ============ AI 助手 Tab ============
            with gr.Tab("🤖 AI助手"):
                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("### 💬 智能任务规划助手")
                        gr.Markdown("告诉我你想让手机自动完成什么任务，我会帮你规划并执行。")
                        # 创建 Chatbot，使用默认的 messages 格式
                        assistant_chatbot = gr.Chatbot(
                            height=420,
                            label="对话记录",
                        )
                        assistant_input = gr.Textbox(
                            label="",
                            placeholder="输入你的需求，按回车发送...",
                            lines=1,
                        )
                        with gr.Row():
                            send_assistant_btn = gr.Button("发送", variant="primary")
                            reset_assistant_btn = gr.Button("🆕 新会话")
                    with gr.Column(scale=1):
                        gr.Markdown("### 📋 任务计划")
                        gr.Markdown("*与助手对话完成后，点击下方按钮生成计划*")
                        assistant_device_selector = gr.CheckboxGroup(
                            label="目标设备（可选）",
                            choices=[],
                            info="不选择则使用当前在线设备",
                        )
                        time_requirement = gr.Textbox(
                            label="时间要求（可选）",
                            placeholder="如：立即执行、每天9点、每2小时...",
                        )
                        generate_plan_btn = gr.Button("📝 生成计划清单", variant="primary", size="lg")
                        plan_preview = gr.Markdown("💡 先和助手对话，描述你的任务需求")
                        plan_state = gr.State({})

                        with gr.Accordion("⚙️ 高级选项", open=False):
                            assistant_use_kb = gr.Checkbox(label="启用知识库", value=True)
                            assistant_parallel = gr.Checkbox(label="多设备并行执行", value=True)
                            with gr.Row():
                                plan_rule_type = gr.Dropdown(
                                    label="调度类型",
                                    choices=["once", "interval", "daily"],
                                    value="once",
                                )
                                plan_once_time = gr.Textbox(
                                    label="一次性时间",
                                    placeholder="2024-01-01T09:00:00",
                                )
                            with gr.Row():
                                plan_interval_minutes = gr.Number(
                                    label="间隔(分钟)",
                                    value=60,
                                )
                                plan_daily_time = gr.Textbox(
                                    label="每日时间(HH:MM)",
                                    value="09:00",
                                )

                        with gr.Row():
                            execute_plan_btn = gr.Button("⚡ 立即执行", variant="primary")
                            import_plan_btn = gr.Button("📥 加入定时任务")
                        plan_status = gr.Textbox(label="", interactive=False, lines=1)

            # ============ 定时任务 Tab ============
            with gr.Tab("⏰ 定时任务"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### 创建/编辑任务")
                        schedule_desc = gr.Textbox(
                            label="任务描述",
                            placeholder="例如：每天早上检查新邮件",
                        )
                        schedule_device_selector = gr.CheckboxGroup(
                            label="目标设备",
                            choices=[],
                            info="不选择则默认在线设备",
                        )
                        schedule_use_kb = gr.Checkbox(label="启用知识库", value=True)
                        schedule_parallel = gr.Checkbox(label="并行执行", value=True)
                        schedule_rule_type = gr.Dropdown(
                            label="调度类型",
                            choices=["once", "interval", "daily"],
                            value="interval",
                        )
                        schedule_once_time = gr.Textbox(
                            label="一次性时间",
                            placeholder="2024-01-01T10:00:00",
                        )
                        schedule_interval_minutes = gr.Number(
                            label="间隔(分钟)",
                            value=120,
                        )
                        schedule_daily_time = gr.Textbox(
                            label="每日时间(HH:MM)",
                            value="09:00",
                        )
                        add_job_btn = gr.Button("➕ 新建/保存", variant="primary")
                    with gr.Column(scale=1):
                        gr.Markdown("### 任务列表")
                        scheduler_table = gr.Markdown("暂无定时任务")
                        scheduler_status = gr.Textbox(label="状态", interactive=False)
                        with gr.Row():
                            remove_job_id = gr.Textbox(label="任务ID", placeholder="粘贴ID操作")
                        with gr.Row():
                            enable_job_btn = gr.Button("启用")
                            disable_job_btn = gr.Button("禁用")
                            delete_job_btn = gr.Button("删除", variant="stop")
                            refresh_job_btn = gr.Button("刷新列表")

            # ========== 设备管理事件绑定 ==========
            # 设备扫描
            scan_btn.click(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            # 选择设备时自动加载信息和刷新屏幕
            device_dropdown.change(
                fn=select_device,
                inputs=[device_dropdown],
                outputs=[device_info, device_custom_name, device_notes, device_favorite, preview_image],
            )

            # WiFi连接 - 连接后自动扫描
            connect_btn.click(
                fn=connect_wifi,
                inputs=[wifi_ip],
                outputs=[wifi_status],
            ).then(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            disconnect_btn.click(
                fn=disconnect_device,
                outputs=[wifi_status],
            ).then(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            # 设备设置保存和删除
            save_device_btn.click(
                fn=save_device_settings,
                inputs=[device_custom_name, device_notes, device_favorite],
                outputs=[device_edit_status],
            ).then(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            delete_device_btn.click(
                fn=delete_saved_device,
                outputs=[device_edit_status],
            ).then(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            # 屏幕操作
            refresh_btn.click(
                fn=refresh_screenshot,
                outputs=[preview_image],
            )

            preview_image.select(
                fn=handle_screen_click,
                outputs=[operation_status, preview_image],
            )

            # 导航按钮
            back_btn.click(
                fn=handle_back,
                outputs=[operation_status, preview_image],
            )

            home_btn.click(
                fn=handle_home,
                outputs=[operation_status, preview_image],
            )

            recent_btn.click(
                fn=handle_recent,
                outputs=[operation_status, preview_image],
            )

            # 滑动操作
            swipe_up_btn.click(
                fn=lambda: handle_swipe("up"),
                outputs=[operation_status, preview_image],
            )

            swipe_down_btn.click(
                fn=lambda: handle_swipe("down"),
                outputs=[operation_status, preview_image],
            )

            swipe_left_btn.click(
                fn=lambda: handle_swipe("left"),
                outputs=[operation_status, preview_image],
            )

            swipe_right_btn.click(
                fn=lambda: handle_swipe("right"),
                outputs=[operation_status, preview_image],
            )

            # 文本输入
            send_text_btn.click(
                fn=handle_input_text,
                inputs=[text_input],
                outputs=[operation_status, preview_image],
            )

            enter_btn.click(
                fn=handle_enter,
                outputs=[operation_status, preview_image],
            )

            # 快捷工具
            install_adb_kb_btn.click(
                fn=handle_install_adb_keyboard,
                outputs=[tool_status],
            )

            enable_adb_kb_btn.click(
                fn=handle_enable_adb_keyboard,
                outputs=[tool_status],
            )

            open_ime_btn.click(
                fn=handle_open_ime_settings,
                outputs=[tool_status, preview_image],
            )

            list_ime_btn.click(
                fn=handle_list_ime,
                outputs=[tool_status],
            )

            open_settings_btn.click(
                fn=handle_open_settings,
                outputs=[tool_status, preview_image],
            )

            clear_cache_btn.click(
                fn=handle_clear_cache,
                outputs=[tool_status],
            )

            # 多文件上传
            upload_files.change(
                fn=analyze_upload_files,
                inputs=[upload_files],
                outputs=[upload_file_info],
            )

            upload_btn.click(
                fn=upload_files_to_devices,
                inputs=[upload_files, multi_device_selector],
                outputs=[upload_status, upload_result_table],
            )

            # 自定义命令
            run_cmd_btn.click(
                fn=handle_custom_command,
                inputs=[custom_cmd],
                outputs=[cmd_output],
            )

            # AI 助手事件
            send_assistant_btn.click(
                fn=assistant_chat,
                inputs=[assistant_input, assistant_chatbot],
                outputs=[assistant_chatbot, assistant_input],
            )

            # 支持回车发送
            assistant_input.submit(
                fn=assistant_chat,
                inputs=[assistant_input, assistant_chatbot],
                outputs=[assistant_chatbot, assistant_input],
            )

            reset_assistant_btn.click(
                fn=reset_assistant_session,
                outputs=[assistant_chatbot, plan_status],
            ).then(
                fn=lambda: ("尚未生成计划", {}),
                outputs=[plan_preview, plan_state],
            )

            generate_plan_btn.click(
                fn=generate_structured_plan,
                inputs=[assistant_device_selector, time_requirement],
                outputs=[plan_preview, plan_state],
            )

            execute_plan_btn.click(
                fn=execute_plan_now,
                inputs=[plan_state, assistant_use_kb, assistant_parallel],
                outputs=[plan_status],
            )

            import_plan_btn.click(
                fn=import_plan_to_scheduler,
                inputs=[
                    plan_state,
                    plan_rule_type,
                    plan_once_time,
                    plan_interval_minutes,
                    plan_daily_time,
                    assistant_use_kb,
                    assistant_parallel,
                ],
                outputs=[plan_status, scheduler_table],
            )

            # 定时任务事件
            add_job_btn.click(
                fn=add_scheduled_job,
                inputs=[
                    schedule_desc,
                    schedule_device_selector,
                    schedule_use_kb,
                    schedule_rule_type,
                    schedule_once_time,
                    schedule_interval_minutes,
                    schedule_daily_time,
                    schedule_parallel,
                ],
                outputs=[scheduler_status, scheduler_table],
            )

            delete_job_btn.click(
                fn=remove_scheduled_job,
                inputs=[remove_job_id],
                outputs=[scheduler_status, scheduler_table],
            )

            enable_job_btn.click(
                fn=enable_scheduled_job,
                inputs=[remove_job_id],
                outputs=[scheduler_status, scheduler_table],
            )

            disable_job_btn.click(
                fn=disable_scheduled_job,
                inputs=[remove_job_id],
                outputs=[scheduler_status, scheduler_table],
            )

            refresh_job_btn.click(
                fn=refresh_scheduled_jobs,
                outputs=[scheduler_table],
            )

            # 初始加载设备列表
            app.load(
                fn=scan_devices,
                outputs=[
                    device_list,
                    device_dropdown,
                    multi_device_selector,
                    task_device_selector,
                    assistant_device_selector,
                    schedule_device_selector,
                ],
            )

            # ============ 设置 Tab ============
            with gr.Tab("⚙️ 设置"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 模型API配置")
                        api_base_url = gr.Textbox(
                            label="API地址",
                            placeholder="https://open.bigmodel.cn/api/paas/v4",
                            value=app_state.settings.api_base_url,
                        )
                        api_key = gr.Textbox(
                            label="API Key",
                            type="password",
                            placeholder="your-api-key",
                            value=app_state.settings.api_key,
                        )
                        model_name = gr.Textbox(
                            label="模型名称",
                            placeholder="autoglm-phone",
                            value=app_state.settings.model_name,
                        )
                        gr.Markdown("### AI助手配置")
                        assistant_api_base = gr.Textbox(
                            label="助手 API Base",
                            placeholder="https://openrouter.ai/api/v1",
                            value=app_state.settings.assistant_api_base,
                        )
                        assistant_api_key = gr.Textbox(
                            label="助手 API Key",
                            type="password",
                            placeholder="openrouter-xxxxx",
                            value=app_state.settings.assistant_api_key,
                        )
                        assistant_model = gr.Textbox(
                            label="助手模型",
                            placeholder="gpt-4o-mini",
                            value=app_state.settings.assistant_model,
                        )
                        with gr.Row():
                            max_tokens = gr.Number(
                                label="最大Token数",
                                value=app_state.settings.max_tokens,
                            )
                            temperature = gr.Slider(
                                label="Temperature",
                                minimum=0,
                                maximum=1,
                                step=0.1,
                                value=app_state.settings.temperature,
                            )
                        test_api_btn = gr.Button("🔗 测试API连接")
                        api_status = gr.Textbox(label="API状态", interactive=False)

                    with gr.Column():
                        gr.Markdown("### 执行参数")
                        max_steps = gr.Number(label="最大步数", value=50)
                        action_delay = gr.Slider(
                            label="操作延迟(秒)",
                            minimum=0.5,
                            maximum=5,
                            step=0.5,
                            value=1.0,
                        )
                        language = gr.Radio(
                            label="语言",
                            choices=["cn", "en"],
                            value="cn",
                        )
                        verbose = gr.Checkbox(label="详细日志", value=True)

                        gr.Markdown("### ADB状态")
                        adb_status = gr.Textbox(label="ADB状态", interactive=False)
                        check_adb_btn = gr.Button("检查ADB")

                        gr.Markdown("---")
                        save_settings_btn = gr.Button("💾 保存设置", variant="primary")
                        settings_status = gr.Textbox(label="", interactive=False)

                # 事件绑定
                test_api_btn.click(
                    fn=test_api,
                    outputs=[api_status],
                )

                check_adb_btn.click(
                    fn=check_adb_status,
                    outputs=[adb_status],
                )

                save_settings_btn.click(
                    fn=save_settings_form,
                    inputs=[
                        api_base_url, api_key, model_name,
                        max_tokens, temperature,
                        max_steps, action_delay, language, verbose,
                        assistant_api_base, assistant_api_key, assistant_model,
                    ],
                    outputs=[settings_status],
                )

                # 加载设置
                def load_all_settings():
                    s = app_state.settings
                    return (
                        s.api_base_url,
                        s.api_key,
                        s.model_name,
                        s.max_tokens,
                        s.temperature,
                        s.max_steps,
                        s.action_delay,
                        s.language,
                        s.verbose,
                        s.assistant_api_base,
                        s.assistant_api_key,
                        s.assistant_model,
                    )

                app.load(
                    fn=load_all_settings,
                    outputs=[
                        api_base_url, api_key, model_name,
                        max_tokens, temperature,
                        max_steps, action_delay, language, verbose,
                        assistant_api_base, assistant_api_key, assistant_model,
                    ],
                )

                app.load(
                    fn=check_adb_status,
                    outputs=[adb_status],
                )

            # 初始加载定时任务
            app.load(
                fn=refresh_scheduled_jobs,
                outputs=[scheduler_table],
            )

        gr.Markdown(
            """
            ---
            **使用说明:**
            1. 在「设备管理」中连接您的手机
            2. 在「知识库」中添加或编辑操作指南 (可选)
            3. 在「设置」中配置API Key
            4. 在「任务执行」中输入任务并开始

            **注意:** 首次使用请先在「设置」中配置您的API Key
            """
        )

    return app


def launch_app(share: bool = False, server_port: int = 7860):
    """启动应用"""
    # 启动前清理缓存，避免磁盘空间不足
    clear_gradio_cache()

    # 确保缓存目录存在
    os.makedirs(GRADIO_CACHE_DIR, exist_ok=True)

    app = create_app()
    # 启用队列以支持实时流式输出
    app.queue(max_size=20)
    app.launch(
        share=share,
        server_port=server_port,
        show_error=True,
        theme=gr.themes.Soft(),
    )
