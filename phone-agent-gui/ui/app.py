"""
Gradio UI 主界面
Phone Agent GUI 的主要用户界面
"""
import gradio as gr
import threading
import time
import io
from PIL import Image
from typing import Optional, List, Tuple

from config.settings import Settings, get_settings, save_settings
from knowledge_base.manager import KnowledgeManager, KnowledgeItem
from core.device_manager import DeviceManager, DeviceInfo
from core.adb_helper import ADBHelper
from core.agent_wrapper import AgentWrapper


# 全局状态
class AppState:
    def __init__(self):
        self.settings = get_settings()
        self.adb_helper = ADBHelper(self.settings.adb_path or None)
        self.device_manager = DeviceManager(self.adb_helper)
        self.knowledge_manager = KnowledgeManager()
        self.agent: Optional[AgentWrapper] = None
        self.current_device: Optional[str] = None
        self.is_task_running = False
        self.task_logs: List[str] = []
        self.current_screenshot: Optional[bytes] = None

    def add_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.task_logs.append(f"[{timestamp}] {message}")
        # 保留最近100条日志
        if len(self.task_logs) > 100:
            self.task_logs = self.task_logs[-100:]


app_state = AppState()


# ==================== 设备管理面板 ====================

def scan_devices() -> str:
    """扫描设备"""
    devices = app_state.device_manager.scan_devices()
    if not devices:
        return "未发现设备。请确保:\n1. 手机已通过USB连接\n2. 已开启USB调试\n3. 已在手机上授权调试"

    result = "发现以下设备:\n\n"
    for d in devices:
        status_icon = "✅" if d.is_online else "❌"
        result += f"{status_icon} {d.display_name} - {d.status_text}\n"

    return result


def get_device_choices() -> List[str]:
    """获取设备选项列表"""
    devices = app_state.device_manager.get_online_devices()
    return [d.device_id for d in devices]


def select_device(device_id: str) -> str:
    """选择设备"""
    if not device_id:
        return "请先选择一个设备"

    app_state.current_device = device_id
    app_state.device_manager.set_current_device(device_id)

    # 获取设备详细信息
    info = app_state.device_manager.get_device_info_detail(device_id)
    return f"""已选择设备: {device_id}
品牌: {info.get('brand', '未知')}
型号: {info.get('model', '未知')}
Android版本: {info.get('android_version', '未知')}
SDK版本: {info.get('sdk_version', '未知')}"""


def connect_wifi(ip_address: str) -> str:
    """WiFi连接设备"""
    if not ip_address:
        return "请输入IP地址"

    # 清理IP地址
    ip_address = ip_address.strip()
    if ":" not in ip_address:
        ip_address = f"{ip_address}:5555"

    ip, port = ip_address.rsplit(":", 1)
    success, message = app_state.device_manager.connect_remote(ip, int(port))

    return message


def disconnect_device() -> str:
    """断开设备连接"""
    success, message = app_state.device_manager.disconnect_all()
    app_state.current_device = None
    return "已断开所有远程连接"


def refresh_screenshot() -> Optional[Image.Image]:
    """刷新屏幕截图"""
    if not app_state.current_device:
        return None

    success, data = app_state.device_manager.take_screenshot(app_state.current_device)
    if success and data:
        app_state.current_screenshot = data
        return Image.open(io.BytesIO(data))
    return None


# ==================== 知识库管理面板 ====================

def get_knowledge_list() -> str:
    """获取知识库列表"""
    items = app_state.knowledge_manager.get_all()
    if not items:
        return "知识库为空，点击「创建默认模板」添加示例"

    result = ""
    for item in items:
        keywords = ", ".join(item.keywords[:3])
        if len(item.keywords) > 3:
            keywords += "..."
        result += f"📄 **{item.title}** (ID: {item.id})\n"
        result += f"   触发词: {keywords}\n\n"

    return result


def get_knowledge_choices() -> List[Tuple[str, str]]:
    """获取知识库选项"""
    items = app_state.knowledge_manager.get_all()
    return [(f"{item.title} ({item.id})", item.id) for item in items]


def load_knowledge_item(item_id: str) -> Tuple[str, str, str]:
    """加载知识条目到编辑区"""
    if not item_id:
        return "", "", ""

    item = app_state.knowledge_manager.get(item_id)
    if not item:
        return "", "", ""

    return item.title, ", ".join(item.keywords), item.content


def save_knowledge_item(item_id: str, title: str, keywords: str, content: str) -> str:
    """保存知识条目"""
    if not title or not content:
        return "标题和内容不能为空"

    # 解析关键词
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        return "请至少添加一个触发词"

    if item_id:
        # 更新现有条目
        item = app_state.knowledge_manager.update(
            item_id, title=title, keywords=keyword_list, content=content
        )
        if item:
            return f"已更新: {title}"
        return "更新失败，条目不存在"
    else:
        # 创建新条目
        item = app_state.knowledge_manager.create(
            title=title, keywords=keyword_list, content=content
        )
        return f"已创建: {title} (ID: {item.id})"


def create_new_knowledge() -> Tuple[str, str, str, str]:
    """新建知识条目"""
    return "", "", "", ""


def delete_knowledge_item(item_id: str) -> str:
    """删除知识条目"""
    if not item_id:
        return "请先选择要删除的条目"

    success = app_state.knowledge_manager.delete(item_id)
    if success:
        return "删除成功"
    return "删除失败，条目不存在"


def create_default_templates() -> str:
    """创建默认模板"""
    app_state.knowledge_manager.create_default_templates()
    return "已创建默认模板"


def export_knowledge(filepath: str) -> str:
    """导出知识库"""
    if not filepath:
        filepath = "knowledge_export.json"
    try:
        app_state.knowledge_manager.export_to_file(filepath)
        return f"已导出到: {filepath}"
    except Exception as e:
        return f"导出失败: {str(e)}"


def import_knowledge(file) -> str:
    """导入知识库"""
    if file is None:
        return "请选择文件"
    try:
        count = app_state.knowledge_manager.import_from_file(file.name)
        return f"成功导入 {count} 条知识"
    except Exception as e:
        return f"导入失败: {str(e)}"


# ==================== 任务执行面板 ====================

def run_task(task: str, use_knowledge: bool) -> Tuple[str, Optional[Image.Image]]:
    """执行任务"""
    if not task:
        return "请输入任务描述", None

    if not app_state.current_device:
        return "请先选择一个设备", None

    if app_state.is_task_running:
        return "已有任务在执行中", None

    # 清空日志
    app_state.task_logs = []
    app_state.add_log(f"开始任务: {task}")

    # 创建Agent
    settings = app_state.settings
    app_state.agent = AgentWrapper(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
        model_name=settings.model_name,
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        device_id=app_state.current_device,
        max_steps=settings.max_steps,
        language=settings.language,
        verbose=settings.verbose,
        knowledge_manager=app_state.knowledge_manager if use_knowledge else None,
        use_knowledge_base=use_knowledge,
    )
    app_state.agent.on_log_callback = app_state.add_log

    # 在后台线程执行任务
    app_state.is_task_running = True

    def execute():
        try:
            for step_result in app_state.agent.run_task(task):
                if step_result.screenshot:
                    app_state.current_screenshot = step_result.screenshot
        except Exception as e:
            app_state.add_log(f"任务执行错误: {str(e)}")
        finally:
            app_state.is_task_running = False

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()

    return "任务已开始执行，请查看日志区域", None


def stop_task() -> str:
    """停止任务"""
    if app_state.agent and app_state.is_task_running:
        app_state.agent.stop()
        return "正在停止任务..."
    return "没有正在执行的任务"


def get_task_logs() -> str:
    """获取任务日志"""
    if not app_state.task_logs:
        return "暂无日志"
    return "\n".join(app_state.task_logs)


def get_task_screenshot() -> Optional[Image.Image]:
    """获取任务截图"""
    if app_state.current_screenshot:
        return Image.open(io.BytesIO(app_state.current_screenshot))
    return None


def get_task_status() -> str:
    """获取任务状态"""
    if app_state.is_task_running:
        return "🔄 任务执行中..."
    return "⏸️ 空闲"


# ==================== 设置面板 ====================

def load_settings() -> Tuple[str, str, str, int, float, int, float, str, bool]:
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

    save_settings(app_state.settings)
    return "设置已保存"


def test_api() -> str:
    """测试API连接"""
    settings = app_state.settings
    agent = AgentWrapper(
        api_base_url=settings.api_base_url,
        api_key=settings.api_key,
        model_name=settings.model_name,
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
        theme=gr.themes.Soft(),
        css="""
        .status-running { color: #22c55e; font-weight: bold; }
        .status-idle { color: #6b7280; }
        .log-area { font-family: monospace; font-size: 12px; }
        """
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
                    with gr.Column(scale=1):
                        gr.Markdown("### 设备扫描")
                        scan_btn = gr.Button("🔍 扫描USB设备", variant="primary")
                        device_list = gr.Textbox(
                            label="设备列表",
                            lines=6,
                            interactive=False,
                        )

                        gr.Markdown("### 选择设备")
                        device_dropdown = gr.Dropdown(
                            label="选择设备",
                            choices=[],
                            interactive=True,
                        )
                        select_btn = gr.Button("选择此设备")
                        device_info = gr.Textbox(
                            label="设备信息",
                            lines=5,
                            interactive=False,
                        )

                        gr.Markdown("### WiFi连接")
                        wifi_ip = gr.Textbox(
                            label="IP地址",
                            placeholder="192.168.1.100:5555",
                        )
                        with gr.Row():
                            connect_btn = gr.Button("连接")
                            disconnect_btn = gr.Button("断开")
                        wifi_status = gr.Textbox(
                            label="连接状态",
                            interactive=False,
                        )

                    with gr.Column(scale=2):
                        gr.Markdown("### 屏幕预览")
                        preview_image = gr.Image(
                            label="设备屏幕",
                            type="pil",
                            height=500,
                        )
                        refresh_btn = gr.Button("🔄 刷新屏幕")

                # 事件绑定
                scan_btn.click(
                    fn=scan_devices,
                    outputs=[device_list],
                ).then(
                    fn=get_device_choices,
                    outputs=[device_dropdown],
                )

                select_btn.click(
                    fn=select_device,
                    inputs=[device_dropdown],
                    outputs=[device_info],
                ).then(
                    fn=refresh_screenshot,
                    outputs=[preview_image],
                )

                connect_btn.click(
                    fn=connect_wifi,
                    inputs=[wifi_ip],
                    outputs=[wifi_status],
                ).then(
                    fn=get_device_choices,
                    outputs=[device_dropdown],
                )

                disconnect_btn.click(
                    fn=disconnect_device,
                    outputs=[wifi_status],
                )

                refresh_btn.click(
                    fn=refresh_screenshot,
                    outputs=[preview_image],
                )

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
                def refresh_knowledge_ui():
                    return get_knowledge_list(), get_knowledge_choices()

                refresh_kb_btn.click(
                    fn=refresh_knowledge_ui,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

                knowledge_dropdown.change(
                    fn=load_knowledge_item,
                    inputs=[knowledge_dropdown],
                    outputs=[kb_title, kb_keywords, kb_content],
                ).then(
                    fn=lambda x: x,
                    inputs=[knowledge_dropdown],
                    outputs=[kb_id],
                )

                new_kb_btn.click(
                    fn=create_new_knowledge,
                    outputs=[kb_id, kb_title, kb_keywords, kb_content],
                )

                save_kb_btn.click(
                    fn=save_knowledge_item,
                    inputs=[kb_id, kb_title, kb_keywords, kb_content],
                    outputs=[save_status],
                ).then(
                    fn=refresh_knowledge_ui,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

                delete_kb_btn.click(
                    fn=delete_knowledge_item,
                    inputs=[kb_id],
                    outputs=[save_status],
                ).then(
                    fn=refresh_knowledge_ui,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                ).then(
                    fn=create_new_knowledge,
                    outputs=[kb_id, kb_title, kb_keywords, kb_content],
                )

                create_template_btn.click(
                    fn=create_default_templates,
                    outputs=[import_export_status],
                ).then(
                    fn=refresh_knowledge_ui,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

                export_btn.click(
                    fn=lambda: export_knowledge("knowledge_export.json"),
                    outputs=[import_export_status],
                )

                import_file.change(
                    fn=import_knowledge,
                    inputs=[import_file],
                    outputs=[import_export_status],
                ).then(
                    fn=refresh_knowledge_ui,
                    outputs=[knowledge_list_display, knowledge_dropdown],
                )

                # 初始加载
                app.load(
                    fn=refresh_knowledge_ui,
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
                        with gr.Row():
                            run_btn = gr.Button("▶️ 开始执行", variant="primary", scale=2)
                            stop_btn = gr.Button("⏹️ 停止", variant="stop", scale=1)

                        task_status = gr.Textbox(
                            label="状态",
                            value="⏸️ 空闲",
                            interactive=False,
                        )

                        gr.Markdown("### 执行日志")
                        log_area = gr.Textbox(
                            label="",
                            lines=15,
                            interactive=False,
                            elem_classes=["log-area"],
                        )
                        refresh_log_btn = gr.Button("🔄 刷新日志")

                    with gr.Column(scale=1):
                        gr.Markdown("### 实时屏幕")
                        task_screenshot = gr.Image(
                            label="",
                            type="pil",
                            height=500,
                        )
                        refresh_task_screenshot_btn = gr.Button("🔄 刷新截图")

                # 事件绑定
                run_btn.click(
                    fn=run_task,
                    inputs=[task_input, use_kb_checkbox],
                    outputs=[task_status, task_screenshot],
                )

                stop_btn.click(
                    fn=stop_task,
                    outputs=[task_status],
                )

                refresh_log_btn.click(
                    fn=get_task_logs,
                    outputs=[log_area],
                )

                refresh_task_screenshot_btn.click(
                    fn=get_task_screenshot,
                    outputs=[task_screenshot],
                )

                # 定时刷新状态和日志
                # (Gradio 4.x 中需要用不同方式实现，这里简化处理)

            # ============ 设置 Tab ============
            with gr.Tab("⚙️ 设置"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 模型API配置")
                        api_base_url = gr.Textbox(
                            label="API地址",
                            placeholder="https://open.bigmodel.cn/api/paas/v4",
                        )
                        api_key = gr.Textbox(
                            label="API Key",
                            type="password",
                            placeholder="your-api-key",
                        )
                        model_name = gr.Textbox(
                            label="模型名称",
                            placeholder="autoglm-phone-9b",
                        )
                        with gr.Row():
                            max_tokens = gr.Number(label="最大Token数", value=3000)
                            temperature = gr.Slider(
                                label="Temperature",
                                minimum=0,
                                maximum=1,
                                step=0.1,
                                value=0.1,
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
                    )

                app.load(
                    fn=load_all_settings,
                    outputs=[
                        api_base_url, api_key, model_name,
                        max_tokens, temperature,
                        max_steps, action_delay, language, verbose,
                    ],
                )

                app.load(
                    fn=check_adb_status,
                    outputs=[adb_status],
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
    app = create_app()
    app.launch(
        share=share,
        server_port=server_port,
        show_error=True,
    )
