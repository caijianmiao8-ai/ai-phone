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
