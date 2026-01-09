"""
API 服务模块

提供 HTTP 接口供 Dify 工作流调用
使用 FastAPI 实现，可与 Gradio 共存
"""

import base64
import io
import json
import threading
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# ==================== 数据模型 ====================

class ExecuteRequest(BaseModel):
    """执行请求"""
    device_id: str
    instruction: str
    wait_after: float = 2.0  # 执行后等待秒数
    timeout: float = 30.0    # 超时时间


class ExecuteResponse(BaseModel):
    """执行响应"""
    success: bool
    message: str
    screenshot: str = ""     # base64 截图
    current_app: str = ""
    execution_time: float = 0.0


class ScreenshotRequest(BaseModel):
    """截图请求"""
    device_id: str


class ScreenshotResponse(BaseModel):
    """截图响应"""
    success: bool
    screenshot: str = ""
    width: int = 0
    height: int = 0
    message: str = ""


class AnalyzeRequest(BaseModel):
    """分析请求"""
    screenshot: str          # base64 截图
    question: str            # 分析问题
    context: str = ""        # 上下文信息


class AnalyzeResponse(BaseModel):
    """分析响应"""
    success: bool
    answer: str = ""
    confidence: float = 0.0
    details: str = ""
    message: str = ""


class DeviceStatusResponse(BaseModel):
    """设备状态响应"""
    device_id: str
    connected: bool
    current_app: str = ""
    screen_size: Dict[str, int] = {}
    message: str = ""


class TaskRequest(BaseModel):
    """任务请求"""
    device_id: str
    task: str
    use_knowledge: bool = True
    max_steps: int = 50
    timeout: float = 300.0


class TaskResponse(BaseModel):
    """任务响应"""
    success: bool
    task_id: str = ""
    message: str = ""


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str  # pending, running, completed, failed
    progress: int = 0
    total_steps: int = 0
    current_action: str = ""
    message: str = ""


# ==================== API 服务器 ====================

class PhoneAgentAPIServer:
    """
    PhoneAgent API 服务器

    提供 RESTful 接口供外部系统（如 Dify）调用
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        agent_wrapper=None,
        device_manager=None,
    ):
        """
        初始化 API 服务器

        Args:
            host: 监听地址
            port: 监听端口
            agent_wrapper: AgentWrapper 实例
            device_manager: DeviceManager 实例
        """
        if not HAS_FASTAPI:
            raise ImportError("需要安装 fastapi 和 uvicorn: pip install fastapi uvicorn")

        self.host = host
        self.port = port
        self.agent_wrapper = agent_wrapper
        self.device_manager = device_manager

        # 任务管理
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._task_counter = 0

        # 创建 FastAPI 应用
        self.app = FastAPI(
            title="PhoneAgent API",
            description="AI 手机控制 API，供 Dify 工作流调用",
            version="1.0.0"
        )

        # 添加 CORS 支持
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # 注册路由
        self._register_routes()

        # 服务器线程
        self._server_thread: Optional[threading.Thread] = None
        self._server: Optional[uvicorn.Server] = None

    def _register_routes(self):
        """注册 API 路由"""

        @self.app.get("/health")
        async def health_check():
            """健康检查"""
            return {"status": "ok", "timestamp": time.time()}

        @self.app.get("/devices")
        async def list_devices():
            """获取设备列表"""
            if not self.device_manager:
                raise HTTPException(status_code=500, detail="设备管理器未初始化")

            devices = self.device_manager.list_devices()
            return {
                "success": True,
                "devices": [
                    {
                        "id": d.device_id,
                        "model": d.model,
                        "status": d.status,
                        "connected": d.status == "device"
                    }
                    for d in devices
                ]
            }

        @self.app.get("/devices/{device_id}/status")
        async def device_status(device_id: str):
            """获取设备状态"""
            if not self.device_manager:
                raise HTTPException(status_code=500, detail="设备管理器未初始化")

            try:
                # 检查设备连接
                devices = self.device_manager.list_devices()
                device = next((d for d in devices if d.device_id == device_id), None)

                if not device:
                    return DeviceStatusResponse(
                        device_id=device_id,
                        connected=False,
                        message="设备未找到"
                    )

                # 获取当前 App
                current_app = ""
                try:
                    from phone_agent.device_factory import get_device_factory
                    factory = get_device_factory()
                    current_app = factory.get_current_app(device_id) or ""
                except:
                    pass

                return DeviceStatusResponse(
                    device_id=device_id,
                    connected=device.status == "device",
                    current_app=current_app,
                    message="OK"
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/screenshot")
        async def capture_screenshot(request: ScreenshotRequest):
            """获取屏幕截图"""
            try:
                from phone_agent.device_factory import get_device_factory
                factory = get_device_factory()

                screenshot = factory.get_screenshot(request.device_id)
                if not screenshot or not screenshot.base64_data:
                    return ScreenshotResponse(
                        success=False,
                        message="截图失败"
                    )

                return ScreenshotResponse(
                    success=True,
                    screenshot=screenshot.base64_data,
                    width=screenshot.width,
                    height=screenshot.height,
                    message="OK"
                )
            except Exception as e:
                return ScreenshotResponse(
                    success=False,
                    message=str(e)
                )

        @self.app.post("/execute")
        async def execute_instruction(request: ExecuteRequest):
            """执行单步指令"""
            if not self.agent_wrapper:
                raise HTTPException(status_code=500, detail="Agent 未初始化")

            start_time = time.time()

            try:
                # 执行指令
                success, message = self.agent_wrapper.execute_single_step(
                    request.device_id,
                    request.instruction,
                    timeout=request.timeout
                )

                # 等待
                if request.wait_after > 0:
                    time.sleep(request.wait_after)

                # 获取执行后截图
                screenshot_b64 = ""
                current_app = ""
                try:
                    from phone_agent.device_factory import get_device_factory
                    factory = get_device_factory()
                    screenshot = factory.get_screenshot(request.device_id)
                    if screenshot:
                        screenshot_b64 = screenshot.base64_data
                    current_app = factory.get_current_app(request.device_id) or ""
                except:
                    pass

                return ExecuteResponse(
                    success=success,
                    message=message,
                    screenshot=screenshot_b64,
                    current_app=current_app,
                    execution_time=time.time() - start_time
                )

            except Exception as e:
                return ExecuteResponse(
                    success=False,
                    message=str(e),
                    execution_time=time.time() - start_time
                )

        @self.app.post("/analyze")
        async def analyze_screenshot(request: AnalyzeRequest):
            """分析截图内容"""
            if not self.agent_wrapper:
                raise HTTPException(status_code=500, detail="Agent 未初始化")

            try:
                # 使用 AI 分析截图
                result = self.agent_wrapper.analyze_screen(
                    screenshot_base64=request.screenshot,
                    question=request.question,
                    context=request.context
                )

                return AnalyzeResponse(
                    success=True,
                    answer=result.get("answer", ""),
                    confidence=result.get("confidence", 0.0),
                    details=result.get("details", ""),
                    message="OK"
                )
            except Exception as e:
                return AnalyzeResponse(
                    success=False,
                    message=str(e)
                )

        @self.app.post("/tasks")
        async def create_task(request: TaskRequest, background_tasks: BackgroundTasks):
            """创建异步任务"""
            if not self.agent_wrapper:
                raise HTTPException(status_code=500, detail="Agent 未初始化")

            # 生成任务 ID
            self._task_counter += 1
            task_id = f"task_{int(time.time())}_{self._task_counter}"

            # 初始化任务状态
            self._tasks[task_id] = {
                "status": "pending",
                "progress": 0,
                "total_steps": 0,
                "current_action": "",
                "message": "任务已创建",
                "result": None
            }

            # 后台执行任务
            background_tasks.add_task(
                self._run_task,
                task_id,
                request.device_id,
                request.task,
                request.use_knowledge,
                request.max_steps,
                request.timeout
            )

            return TaskResponse(
                success=True,
                task_id=task_id,
                message="任务已创建"
            )

        @self.app.get("/tasks/{task_id}")
        async def get_task_status(task_id: str):
            """获取任务状态"""
            if task_id not in self._tasks:
                raise HTTPException(status_code=404, detail="任务不存在")

            task = self._tasks[task_id]
            return TaskStatusResponse(
                task_id=task_id,
                status=task["status"],
                progress=task["progress"],
                total_steps=task["total_steps"],
                current_action=task["current_action"],
                message=task["message"]
            )

        @self.app.delete("/tasks/{task_id}")
        async def cancel_task(task_id: str):
            """取消任务"""
            if task_id not in self._tasks:
                raise HTTPException(status_code=404, detail="任务不存在")

            task = self._tasks[task_id]
            if task["status"] == "running":
                # 尝试停止任务
                if self.agent_wrapper:
                    self.agent_wrapper.stop_task(task_id)
                task["status"] = "cancelled"
                task["message"] = "任务已取消"

            return {"success": True, "message": "任务已取消"}

    async def _run_task(
        self,
        task_id: str,
        device_id: str,
        task: str,
        use_knowledge: bool,
        max_steps: int,
        timeout: float
    ):
        """后台运行任务"""
        task_state = self._tasks[task_id]
        task_state["status"] = "running"

        try:
            def on_progress(step: int, total: int, action: str):
                task_state["progress"] = step
                task_state["total_steps"] = total
                task_state["current_action"] = action

            success, message = self.agent_wrapper.run_task(
                device_id=device_id,
                task=task,
                use_knowledge=use_knowledge,
                max_steps=max_steps,
                on_progress=on_progress
            )

            task_state["status"] = "completed" if success else "failed"
            task_state["message"] = message
            task_state["result"] = {"success": success, "message": message}

        except Exception as e:
            task_state["status"] = "failed"
            task_state["message"] = str(e)

    def start(self):
        """启动 API 服务器"""
        if self._server_thread and self._server_thread.is_alive():
            return

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning"
        )
        self._server = uvicorn.Server(config)

        self._server_thread = threading.Thread(
            target=self._server.run,
            daemon=True
        )
        self._server_thread.start()

        print(f"📡 PhoneAgent API 服务器已启动: http://{self.host}:{self.port}")
        print(f"   API 文档: http://{self.host}:{self.port}/docs")

    def stop(self):
        """停止 API 服务器"""
        if self._server:
            self._server.should_exit = True


# 全局实例
_api_server: Optional[PhoneAgentAPIServer] = None


def get_api_server() -> Optional[PhoneAgentAPIServer]:
    """获取 API 服务器实例"""
    return _api_server


def init_api_server(
    agent_wrapper=None,
    device_manager=None,
    host: str = "0.0.0.0",
    port: int = 8765
) -> Optional[PhoneAgentAPIServer]:
    """
    初始化并启动 API 服务器

    Args:
        agent_wrapper: AgentWrapper 实例
        device_manager: DeviceManager 实例
        host: 监听地址
        port: 监听端口

    Returns:
        API 服务器实例
    """
    global _api_server

    if not HAS_FASTAPI:
        print("⚠️ FastAPI 未安装，API 服务器不可用")
        print("   安装命令: pip install fastapi uvicorn")
        return None

    try:
        _api_server = PhoneAgentAPIServer(
            host=host,
            port=port,
            agent_wrapper=agent_wrapper,
            device_manager=device_manager
        )
        _api_server.start()
        return _api_server
    except Exception as e:
        print(f"❌ API 服务器启动失败: {e}")
        return None
