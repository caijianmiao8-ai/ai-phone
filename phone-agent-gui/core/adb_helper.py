"""
ADB工具辅助模块
管理内置ADB工具的路径和环境配置
"""
import os
import subprocess
import platform
from typing import Optional, Tuple


class ADBHelper:
    """ADB工具辅助类"""

    def __init__(self, custom_adb_path: str = None):
        self.custom_adb_path = custom_adb_path
        self._adb_path = None

    def get_bundled_adb_path(self) -> str:
        """获取内置ADB工具路径"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        adb_dir = os.path.join(base_dir, "adb")

        if platform.system() == "Windows":
            return os.path.join(adb_dir, "adb.exe")
        else:
            return os.path.join(adb_dir, "adb")

    def get_adb_path(self) -> str:
        """获取ADB可执行文件路径"""
        if self._adb_path:
            return self._adb_path

        # 优先使用自定义路径
        if self.custom_adb_path and os.path.exists(self.custom_adb_path):
            self._adb_path = self.custom_adb_path
            return self._adb_path

        # 使用内置ADB
        bundled = self.get_bundled_adb_path()
        if os.path.exists(bundled):
            self._adb_path = bundled
            return self._adb_path

        # 尝试系统PATH中的adb
        try:
            result = subprocess.run(
                ["adb", "version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5
            )
            if result.returncode == 0:
                self._adb_path = "adb"
                return self._adb_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return ""

    def is_available(self) -> bool:
        """检查ADB是否可用"""
        adb_path = self.get_adb_path()
        if not adb_path:
            return False

        try:
            result = subprocess.run(
                [adb_path, "version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_version(self) -> str:
        """获取ADB版本"""
        adb_path = self.get_adb_path()
        if not adb_path:
            return "未找到ADB"

        try:
            result = subprocess.run(
                [adb_path, "version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5
            )
            if result.returncode == 0:
                # 提取版本号
                lines = result.stdout.strip().split("\n")
                if lines:
                    return lines[0]
            return "版本未知"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return "获取版本失败"

    def run_command(self, args: list, timeout: int = 30) -> Tuple[bool, str]:
        """运行ADB命令"""
        adb_path = self.get_adb_path()
        if not adb_path:
            return False, "ADB不可用"

        try:
            cmd = [adb_path] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "命令执行超时"
        except Exception as e:
            return False, str(e)

    def start_server(self) -> Tuple[bool, str]:
        """启动ADB服务"""
        return self.run_command(["start-server"])

    def kill_server(self) -> Tuple[bool, str]:
        """停止ADB服务"""
        return self.run_command(["kill-server"])

    def restart_server(self) -> Tuple[bool, str]:
        """重启ADB服务"""
        self.kill_server()
        return self.start_server()

    def setup_environment(self):
        """设置ADB环境变量"""
        adb_path = self.get_adb_path()
        if adb_path and adb_path != "adb":
            adb_dir = os.path.dirname(adb_path)
            current_path = os.environ.get("PATH", "")
            if adb_dir not in current_path:
                os.environ["PATH"] = adb_dir + os.pathsep + current_path
