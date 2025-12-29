"""
设备管理模块
管理Android设备的连接、扫描等操作
"""
import subprocess
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from .adb_helper import ADBHelper
from .device_registry import DeviceRegistry, SavedDevice


@dataclass
class DeviceInfo:
    """设备信息（运行时状态）"""
    device_id: str
    status: str  # device, offline, unauthorized
    model: str = ""
    is_remote: bool = False
    custom_name: str = ""      # 从注册表获取的自定义名称
    is_favorite: bool = False  # 是否收藏
    brand: str = ""            # 品牌

    @property
    def display_name(self) -> str:
        """显示名称：优先使用自定义名称"""
        if self.custom_name:
            return self.custom_name
        if self.model:
            if self.brand:
                return f"{self.brand} {self.model}"
            return self.model
        return self.device_id

    @property
    def full_display_name(self) -> str:
        """完整显示名称：包含设备ID"""
        name = self.display_name
        if self.custom_name or self.model:
            return f"{name} ({self.device_id})"
        return name

    @property
    def is_online(self) -> bool:
        return self.status == "device"

    @property
    def status_text(self) -> str:
        status_map = {
            "device": "已连接",
            "offline": "离线",
            "unauthorized": "未授权",
        }
        return status_map.get(self.status, self.status)


class DeviceManager:
    """设备管理器"""

    def __init__(self, adb_helper: ADBHelper = None, device_registry: DeviceRegistry = None):
        self.adb_helper = adb_helper or ADBHelper()
        self.registry = device_registry or DeviceRegistry()
        self._current_device: Optional[str] = None

    def scan_devices(self, include_saved_offline: bool = True) -> List[DeviceInfo]:
        """
        扫描所有已连接的设备，并合并已保存设备信息

        Args:
            include_saved_offline: 是否包含已保存但离线的设备
        """
        success, output = self.adb_helper.run_command(["devices", "-l"])
        if not success:
            # 如果扫描失败，返回已保存的设备（标记为离线）
            if include_saved_offline:
                return self._get_saved_devices_as_offline()
            return []

        devices = []
        online_device_ids = set()
        lines = output.strip().split("\n")

        for line in lines[1:]:  # 跳过第一行 "List of devices attached"
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) >= 2:
                device_id = parts[0]
                status = parts[1]
                online_device_ids.add(device_id)

                # 提取设备型号
                model = ""
                model_match = re.search(r"model:(\S+)", line)
                if model_match:
                    model = model_match.group(1).replace("_", " ")

                is_remote = ":" in device_id

                # 从注册表获取已保存的信息
                saved = self.registry.get(device_id)
                custom_name = saved.custom_name if saved else ""
                is_favorite = saved.is_favorite if saved else False
                brand = saved.brand if saved else ""

                # 如果是新设备或在线设备，更新注册表
                if status == "device":
                    self._update_registry_for_online_device(device_id, model, is_remote)

                devices.append(DeviceInfo(
                    device_id=device_id,
                    status=status,
                    model=model or (saved.model if saved else ""),
                    is_remote=is_remote,
                    custom_name=custom_name,
                    is_favorite=is_favorite,
                    brand=brand
                ))

        # 添加已保存但当前离线的设备
        if include_saved_offline:
            for saved in self.registry.get_all():
                if saved.device_id not in online_device_ids:
                    devices.append(DeviceInfo(
                        device_id=saved.device_id,
                        status="offline",
                        model=saved.model,
                        is_remote=saved.device_type == "wifi",
                        custom_name=saved.custom_name,
                        is_favorite=saved.is_favorite,
                        brand=saved.brand
                    ))

        # 按收藏状态和在线状态排序
        devices.sort(key=lambda d: (not d.is_favorite, not d.is_online, d.display_name))

        return devices

    def _get_saved_devices_as_offline(self) -> List[DeviceInfo]:
        """将已保存的设备作为离线设备返回"""
        devices = []
        for saved in self.registry.get_all():
            devices.append(DeviceInfo(
                device_id=saved.device_id,
                status="offline",
                model=saved.model,
                is_remote=saved.device_type == "wifi",
                custom_name=saved.custom_name,
                is_favorite=saved.is_favorite,
                brand=saved.brand
            ))
        return devices

    def _update_registry_for_online_device(self, device_id: str, model: str, is_remote: bool):
        """更新在线设备的注册表信息"""
        saved = self.registry.get(device_id)
        if saved:
            # 更新连接时间
            saved.update_connection_time()
            if model and not saved.model:
                saved.model = model
            self.registry.save()
        else:
            # 新设备，获取详细信息并保存
            info = self.get_device_info_detail(device_id)
            new_device = SavedDevice(
                device_id=device_id,
                device_type="wifi" if is_remote else "usb",
                connection_address=device_id if is_remote else "",
                brand=info.get("brand", ""),
                model=info.get("model", "") or model,
                android_version=info.get("android_version", ""),
                sdk_version=info.get("sdk_version", ""),
            )
            new_device.update_connection_time()
            self.registry.add_or_update(new_device)

    def get_online_devices(self) -> List[DeviceInfo]:
        """获取所有在线设备"""
        return [d for d in self.scan_devices() if d.is_online]

    def connect_remote(self, ip_address: str, port: int = 5555) -> Tuple[bool, str]:
        """连接远程设备（WiFi调试）"""
        address = f"{ip_address}:{port}"
        success, output = self.adb_helper.run_command(["connect", address], timeout=10)

        if success and ("connected" in output.lower() or "already" in output.lower()):
            return True, f"已连接到 {address}"
        else:
            return False, output or "连接失败"

    def disconnect_remote(self, ip_address: str, port: int = 5555) -> Tuple[bool, str]:
        """断开远程设备连接"""
        address = f"{ip_address}:{port}"
        success, output = self.adb_helper.run_command(["disconnect", address])
        return success, output

    def disconnect_all(self) -> Tuple[bool, str]:
        """断开所有远程连接"""
        return self.adb_helper.run_command(["disconnect"])

    def enable_tcpip(self, device_id: str = None, port: int = 5555) -> Tuple[bool, str]:
        """在设备上启用TCP/IP调试"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["tcpip", str(port)])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"已在端口 {port} 启用TCP/IP调试"
        return False, output

    def get_device_ip(self, device_id: str = None) -> Optional[str]:
        """获取设备的IP地址"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "ip", "route"])

        success, output = self.adb_helper.run_command(args)
        if success:
            # 解析IP地址
            match = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", output)
            if match:
                return match.group(1)
        return None

    def set_current_device(self, device_id: str):
        """设置当前使用的设备"""
        self._current_device = device_id

    def get_current_device(self) -> Optional[str]:
        """获取当前设备"""
        return self._current_device

    def take_screenshot(self, device_id: str = None) -> Tuple[bool, bytes]:
        """截取设备屏幕"""
        adb_path = self.adb_helper.get_adb_path()
        if not adb_path:
            return False, b""

        args = [adb_path]
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["exec-out", "screencap", "-p"])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout:
                return True, result.stdout
            return False, b""
        except Exception:
            return False, b""

    def get_device_info_detail(self, device_id: str) -> dict:
        """获取设备详细信息"""
        info = {
            "device_id": device_id,
            "brand": "",
            "model": "",
            "android_version": "",
            "sdk_version": "",
        }

        props = [
            ("brand", "ro.product.brand"),
            ("model", "ro.product.model"),
            ("android_version", "ro.build.version.release"),
            ("sdk_version", "ro.build.version.sdk"),
        ]

        for key, prop in props:
            args = ["-s", device_id, "shell", "getprop", prop]
            success, output = self.adb_helper.run_command(args)
            if success:
                info[key] = output.strip()

        return info

    # ==================== 远程操作功能 ====================

    def get_screen_size(self, device_id: str = None) -> Tuple[int, int]:
        """获取屏幕分辨率"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "wm", "size"])

        success, output = self.adb_helper.run_command(args)
        if success:
            match = re.search(r"(\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
        return 1080, 1920  # 默认分辨率

    def tap(self, x: int, y: int, device_id: str = None) -> Tuple[bool, str]:
        """点击屏幕指定坐标"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "input", "tap", str(x), str(y)])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"点击 ({x}, {y})"
        return False, output or "点击失败"

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration: int = 300, device_id: str = None) -> Tuple[bool, str]:
        """滑动屏幕"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "input", "swipe",
                    str(x1), str(y1), str(x2), str(y2), str(duration)])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"滑动 ({x1},{y1}) -> ({x2},{y2})"
        return False, output or "滑动失败"

    def long_press(self, x: int, y: int, duration: int = 1000,
                   device_id: str = None) -> Tuple[bool, str]:
        """长按屏幕"""
        # 长按实际上是原地滑动
        return self.swipe(x, y, x, y, duration, device_id)

    def input_text(self, text: str, device_id: str = None) -> Tuple[bool, str]:
        """输入文本（需要先聚焦输入框）"""
        import base64

        args = []
        if device_id:
            args.extend(["-s", device_id])

        # 使用 ADB Keyboard 广播方式输入（支持中文）
        # 必须使用 Base64 编码，这是 ADB Keyboard 的标准接口
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("utf-8")
        args.extend(["shell", "am", "broadcast", "-a",
                    "ADB_INPUT_B64", "--es", "msg", encoded_text])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"已输入文本"

        # 如果 ADB Keyboard 不可用，回退到基础输入（仅英文）
        args = []
        if device_id:
            args.extend(["-s", device_id])
        # 转义特殊字符
        escaped_text = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
        args.extend(["shell", "input", "text", escaped_text])
        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"已输入文本 (基础模式，仅支持英文)"
        return False, output or "输入失败"

    def press_key(self, keycode: str, device_id: str = None) -> Tuple[bool, str]:
        """按下按键"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "input", "keyevent", keycode])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"按键 {keycode}"
        return False, output or "按键失败"

    def press_back(self, device_id: str = None) -> Tuple[bool, str]:
        """返回键"""
        return self.press_key("KEYCODE_BACK", device_id)

    def press_home(self, device_id: str = None) -> Tuple[bool, str]:
        """主页键"""
        return self.press_key("KEYCODE_HOME", device_id)

    def press_recent(self, device_id: str = None) -> Tuple[bool, str]:
        """最近任务键"""
        return self.press_key("KEYCODE_APP_SWITCH", device_id)

    def press_enter(self, device_id: str = None) -> Tuple[bool, str]:
        """回车键"""
        return self.press_key("KEYCODE_ENTER", device_id)

    def install_apk(self, apk_path: str, device_id: str = None) -> Tuple[bool, str]:
        """安装APK（支持大文件，超时5分钟）"""
        import os
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["install", "-r", apk_path])

        # 根据文件大小动态调整超时时间
        # 基础60秒 + 每10MB额外30秒，最长10分钟
        try:
            file_size_mb = os.path.getsize(apk_path) / (1024 * 1024)
            timeout = min(60 + int(file_size_mb / 10) * 30, 600)
        except Exception:
            timeout = 300  # 默认5分钟

        success, output = self.adb_helper.run_command(args, timeout=timeout)
        if success and "Success" in output:
            return True, "安装成功"
        return False, output or "安装失败"

    def install_apk_from_url(self, url: str, device_id: str = None) -> Tuple[bool, str]:
        """从URL下载并安装APK"""
        import tempfile
        import urllib.request

        try:
            # 下载APK到临时文件
            with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as f:
                urllib.request.urlretrieve(url, f.name)
                return self.install_apk(f.name, device_id)
        except Exception as e:
            return False, f"下载失败: {str(e)}"

    def open_settings(self, device_id: str = None) -> Tuple[bool, str]:
        """打开系统设置"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "am", "start", "-a", "android.settings.SETTINGS"])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, "已打开设置"
        return False, output or "打开失败"

    def open_language_settings(self, device_id: str = None) -> Tuple[bool, str]:
        """打开语言和输入法设置"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "am", "start", "-a",
                    "android.settings.INPUT_METHOD_SETTINGS"])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, "已打开输入法设置"
        return False, output or "打开失败"

    def set_ime(self, ime_id: str, device_id: str = None) -> Tuple[bool, str]:
        """设置当前输入法"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "ime", "set", ime_id])

        success, output = self.adb_helper.run_command(args)
        if success:
            return True, f"已切换输入法: {ime_id}"
        return False, output or "切换失败"

    def enable_adb_keyboard(self, device_id: str = None) -> Tuple[bool, str]:
        """启用ADB Keyboard输入法"""
        # 先启用
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "ime", "enable", "com.android.adbkeyboard/.AdbIME"])
        self.adb_helper.run_command(args)

        # 再设置为当前输入法
        return self.set_ime("com.android.adbkeyboard/.AdbIME", device_id)

    def list_ime(self, device_id: str = None) -> Tuple[bool, str]:
        """列出所有输入法"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", "ime", "list", "-a"])

        return self.adb_helper.run_command(args)

    def run_shell_command(self, command: str, device_id: str = None) -> Tuple[bool, str]:
        """执行自定义shell命令"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["shell", command])

        return self.adb_helper.run_command(args, timeout=30)

    def run_adb_command(self, command: str, device_id: str = None) -> Tuple[bool, str]:
        """执行自定义ADB命令"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        # 解析命令字符串为参数列表
        cmd_parts = command.split()
        args.extend(cmd_parts)

        return self.adb_helper.run_command(args, timeout=30)

    # ==================== 设备注册表操作 ====================

    def set_device_name(self, device_id: str, name: str) -> bool:
        """设置设备自定义名称"""
        return self.registry.set_custom_name(device_id, name)

    def set_device_favorite(self, device_id: str, is_favorite: bool) -> bool:
        """设置设备收藏状态"""
        return self.registry.set_favorite(device_id, is_favorite)

    def set_device_notes(self, device_id: str, notes: str) -> bool:
        """设置设备备注"""
        return self.registry.set_notes(device_id, notes)

    def get_saved_device(self, device_id: str) -> Optional[SavedDevice]:
        """获取已保存的设备信息"""
        return self.registry.get(device_id)

    def remove_saved_device(self, device_id: str) -> bool:
        """删除已保存的设备"""
        return self.registry.remove(device_id)

    def get_device_display_info(self, device_id: str) -> dict:
        """获取设备的显示信息（合并在线状态和保存信息）"""
        saved = self.registry.get(device_id)

        # 直接用 adb devices 检查在线状态，不重新扫描全部
        is_online = self._check_device_online(device_id)

        # 只有在线时才获取详细信息
        online_info = {}
        if is_online:
            online_info = self.get_device_info_detail(device_id)

        result = {
            "device_id": device_id,
            "is_online": is_online,
            "status": "已连接" if is_online else "离线",
        }

        if saved:
            result.update({
                "custom_name": saved.custom_name,
                "display_name": saved.display_name,
                "brand": saved.brand or online_info.get("brand", ""),
                "model": saved.model or online_info.get("model", ""),
                "android_version": saved.android_version or online_info.get("android_version", ""),
                "sdk_version": saved.sdk_version or online_info.get("sdk_version", ""),
                "device_type": saved.device_type,
                "is_favorite": saved.is_favorite,
                "notes": saved.notes,
                "last_connected": saved.last_connected,
            })
        else:
            result.update({
                "custom_name": "",
                "display_name": device_id,
                "brand": online_info.get("brand", ""),
                "model": online_info.get("model", ""),
                "android_version": online_info.get("android_version", ""),
                "sdk_version": online_info.get("sdk_version", ""),
                "device_type": "wifi" if ":" in device_id else "usb",
                "is_favorite": False,
                "notes": "",
                "last_connected": "",
            })

        return result

    def _check_device_online(self, device_id: str) -> bool:
        """快速检查设备是否在线"""
        success, output = self.adb_helper.run_command(["devices"])
        if not success:
            return False
        # 检查设备ID是否在输出中且状态为device
        for line in output.strip().split("\n"):
            if line.startswith(device_id) and "\tdevice" in line:
                return True
        return False

    # ==================== scrcpy 投屏功能 ====================

    # 存储运行中的 scrcpy 进程
    _scrcpy_processes: dict = {}

    def is_scrcpy_available(self) -> Tuple[bool, str]:
        """检查 scrcpy 是否可用"""
        import shutil
        import platform

        # 检查 scrcpy 是否在 PATH 中
        scrcpy_path = shutil.which("scrcpy")
        if scrcpy_path:
            return True, scrcpy_path

        # Windows 下检查常见安装位置
        if platform.system() == "Windows":
            common_paths = [
                r"C:\scrcpy\scrcpy.exe",
                r"C:\Program Files\scrcpy\scrcpy.exe",
                r"C:\Program Files (x86)\scrcpy\scrcpy.exe",
            ]
            for path in common_paths:
                import os
                if os.path.exists(path):
                    return True, path

        return False, ""

    def start_scrcpy(self, device_id: str = None, options: dict = None) -> Tuple[bool, str]:
        """
        启动 scrcpy 投屏

        Args:
            device_id: 设备ID，不指定则使用默认设备
            options: 可选参数
                - max_size: 最大分辨率 (如 1024)
                - bit_rate: 比特率 (如 "8M")
                - max_fps: 最大帧率 (如 30)
                - window_title: 窗口标题
                - stay_awake: 保持唤醒
                - turn_screen_off: 关闭手机屏幕
                - show_touches: 显示触摸点

        Returns:
            (success, message)
        """
        import platform

        # 检查 scrcpy 是否可用
        available, scrcpy_path = self.is_scrcpy_available()
        if not available:
            return False, "scrcpy 未安装。请从 https://github.com/Genymobile/scrcpy 下载安装"

        # 如果该设备已有 scrcpy 运行，先停止
        if device_id and device_id in self._scrcpy_processes:
            self.stop_scrcpy(device_id)

        # 构建命令
        cmd = [scrcpy_path]

        if device_id:
            cmd.extend(["-s", device_id])

        # 应用选项
        options = options or {}

        if options.get("max_size"):
            cmd.extend(["--max-size", str(options["max_size"])])
        else:
            cmd.extend(["--max-size", "1024"])  # 默认限制分辨率

        if options.get("bit_rate"):
            cmd.extend(["--video-bit-rate", options["bit_rate"]])

        if options.get("max_fps"):
            cmd.extend(["--max-fps", str(options["max_fps"])])

        if options.get("window_title"):
            cmd.extend(["--window-title", options["window_title"]])
        elif device_id:
            cmd.extend(["--window-title", f"投屏 - {device_id}"])

        if options.get("stay_awake"):
            cmd.append("--stay-awake")

        if options.get("turn_screen_off"):
            cmd.append("--turn-screen-off")

        if options.get("show_touches"):
            cmd.append("--show-touches")

        try:
            # 在后台启动 scrcpy
            if platform.system() == "Windows":
                # Windows: 使用 CREATE_NEW_CONSOLE 避免阻塞
                process = subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                # Linux/Mac: 直接后台运行
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            # 记录进程
            key = device_id or "default"
            self._scrcpy_processes[key] = process

            return True, "投屏已启动"

        except Exception as e:
            return False, f"启动失败: {str(e)}"

    def stop_scrcpy(self, device_id: str = None) -> Tuple[bool, str]:
        """停止 scrcpy 投屏"""
        key = device_id or "default"

        if key not in self._scrcpy_processes:
            return False, "没有运行中的投屏"

        try:
            process = self._scrcpy_processes[key]
            process.terminate()
            process.wait(timeout=3)
            del self._scrcpy_processes[key]
            return True, "投屏已停止"
        except Exception as e:
            # 强制杀死
            try:
                process.kill()
                del self._scrcpy_processes[key]
                return True, "投屏已强制停止"
            except Exception:
                return False, f"停止失败: {str(e)}"

    def is_scrcpy_running(self, device_id: str = None) -> bool:
        """检查 scrcpy 是否正在运行"""
        key = device_id or "default"
        if key not in self._scrcpy_processes:
            return False

        process = self._scrcpy_processes[key]
        return process.poll() is None  # None 表示仍在运行
