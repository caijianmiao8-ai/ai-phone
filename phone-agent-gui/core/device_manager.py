"""
设备管理模块
管理Android设备的连接、扫描等操作
"""
import subprocess
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from .adb_helper import ADBHelper


@dataclass
class DeviceInfo:
    """设备信息"""
    device_id: str
    status: str  # device, offline, unauthorized
    model: str = ""
    is_remote: bool = False

    @property
    def display_name(self) -> str:
        """显示名称"""
        if self.model:
            return f"{self.model} ({self.device_id})"
        return self.device_id

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

    def __init__(self, adb_helper: ADBHelper = None):
        self.adb_helper = adb_helper or ADBHelper()
        self._current_device: Optional[str] = None

    def scan_devices(self) -> List[DeviceInfo]:
        """扫描所有已连接的设备"""
        success, output = self.adb_helper.run_command(["devices", "-l"])
        if not success:
            return []

        devices = []
        lines = output.strip().split("\n")

        for line in lines[1:]:  # 跳过第一行 "List of devices attached"
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) >= 2:
                device_id = parts[0]
                status = parts[1]

                # 提取设备型号
                model = ""
                model_match = re.search(r"model:(\S+)", line)
                if model_match:
                    model = model_match.group(1).replace("_", " ")

                is_remote = ":" in device_id

                devices.append(DeviceInfo(
                    device_id=device_id,
                    status=status,
                    model=model,
                    is_remote=is_remote
                ))

        return devices

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
        args = []
        if device_id:
            args.extend(["-s", device_id])
        # 使用 ADB Keyboard 广播方式输入（支持中文）
        args.extend(["shell", "am", "broadcast", "-a",
                    "ADB_INPUT_TEXT", "--es", "msg", text])

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
            return True, f"已输入文本 (基础模式)"
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
        """安装APK"""
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["install", "-r", apk_path])

        success, output = self.adb_helper.run_command(args, timeout=60)
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
