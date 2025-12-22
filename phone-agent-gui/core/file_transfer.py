"""
文件传输管理器
支持多文件上传、多种文件类型
"""
import os
import subprocess
from dataclasses import dataclass
from typing import List, Tuple, Optional, Callable
from enum import Enum

from .adb_helper import ADBHelper


class FileType(Enum):
    """文件类型枚举"""
    APK = "apk"
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"
    OTHER = "other"


@dataclass
class FileInfo:
    """文件信息"""
    path: str                    # 本地文件路径
    name: str                    # 文件名
    size: int                    # 文件大小（字节）
    file_type: FileType          # 文件类型
    target_path: str             # 目标路径

    @property
    def size_display(self) -> str:
        """人类可读的文件大小"""
        if self.size < 1024:
            return f"{self.size} B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f} KB"
        elif self.size < 1024 * 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.size / (1024 * 1024 * 1024):.2f} GB"

    @property
    def action_display(self) -> str:
        """操作描述"""
        if self.file_type == FileType.APK:
            return "安装应用"
        else:
            return f"推送到 {self.target_path}"


@dataclass
class TransferResult:
    """传输结果"""
    file_info: FileInfo
    success: bool
    message: str
    device_id: str


class FileTransferManager:
    """文件传输管理器"""

    # 文件扩展名到类型的映射
    EXTENSION_MAP = {
        # APK
        ".apk": FileType.APK,
        ".xapk": FileType.APK,

        # 视频
        ".mp4": FileType.VIDEO,
        ".mkv": FileType.VIDEO,
        ".avi": FileType.VIDEO,
        ".mov": FileType.VIDEO,
        ".wmv": FileType.VIDEO,
        ".flv": FileType.VIDEO,
        ".webm": FileType.VIDEO,
        ".m4v": FileType.VIDEO,
        ".3gp": FileType.VIDEO,

        # 音频
        ".mp3": FileType.AUDIO,
        ".wav": FileType.AUDIO,
        ".flac": FileType.AUDIO,
        ".aac": FileType.AUDIO,
        ".ogg": FileType.AUDIO,
        ".wma": FileType.AUDIO,
        ".m4a": FileType.AUDIO,

        # 图片
        ".jpg": FileType.IMAGE,
        ".jpeg": FileType.IMAGE,
        ".png": FileType.IMAGE,
        ".gif": FileType.IMAGE,
        ".bmp": FileType.IMAGE,
        ".webp": FileType.IMAGE,
        ".svg": FileType.IMAGE,

        # 文档
        ".pdf": FileType.DOCUMENT,
        ".doc": FileType.DOCUMENT,
        ".docx": FileType.DOCUMENT,
        ".xls": FileType.DOCUMENT,
        ".xlsx": FileType.DOCUMENT,
        ".ppt": FileType.DOCUMENT,
        ".pptx": FileType.DOCUMENT,
        ".txt": FileType.DOCUMENT,
        ".csv": FileType.DOCUMENT,
        ".json": FileType.DOCUMENT,
        ".xml": FileType.DOCUMENT,
    }

    # 文件类型到目标目录的映射
    TARGET_DIRS = {
        FileType.APK: None,  # APK 直接安装，不推送
        FileType.VIDEO: "/sdcard/Movies/",
        FileType.AUDIO: "/sdcard/Music/",
        FileType.IMAGE: "/sdcard/Pictures/",
        FileType.DOCUMENT: "/sdcard/Documents/",
        FileType.OTHER: "/sdcard/Download/",
    }

    # 支持的文件扩展名列表（用于 Gradio file_types）
    SUPPORTED_EXTENSIONS = list(EXTENSION_MAP.keys()) + [".zip", ".rar", ".7z"]

    def __init__(self, adb_helper: ADBHelper = None):
        self.adb_helper = adb_helper or ADBHelper()

    def get_file_type(self, filepath: str) -> FileType:
        """根据文件扩展名获取文件类型"""
        ext = os.path.splitext(filepath)[1].lower()
        return self.EXTENSION_MAP.get(ext, FileType.OTHER)

    def get_target_path(self, filepath: str) -> str:
        """获取文件在设备上的目标路径"""
        file_type = self.get_file_type(filepath)
        target_dir = self.TARGET_DIRS.get(file_type, "/sdcard/Download/")
        if target_dir is None:
            return ""  # APK 不需要目标路径
        filename = os.path.basename(filepath)
        return f"{target_dir}{filename}"

    def analyze_file(self, filepath: str) -> Optional[FileInfo]:
        """分析文件，返回文件信息"""
        if not os.path.exists(filepath):
            return None

        try:
            size = os.path.getsize(filepath)
            name = os.path.basename(filepath)
            file_type = self.get_file_type(filepath)
            target_path = self.get_target_path(filepath)

            return FileInfo(
                path=filepath,
                name=name,
                size=size,
                file_type=file_type,
                target_path=target_path
            )
        except Exception:
            return None

    def analyze_files(self, filepaths: List[str]) -> List[FileInfo]:
        """批量分析文件"""
        results = []
        for filepath in filepaths:
            info = self.analyze_file(filepath)
            if info:
                results.append(info)
        return results

    def _calculate_timeout(self, file_size: int) -> int:
        """根据文件大小计算超时时间"""
        # 基础60秒 + 每10MB额外30秒，最长10分钟
        size_mb = file_size / (1024 * 1024)
        timeout = 60 + int(size_mb / 10) * 30
        return min(timeout, 600)

    def install_apk(self, filepath: str, device_id: str = None) -> Tuple[bool, str]:
        """安装APK文件"""
        if not os.path.exists(filepath):
            return False, "文件不存在"

        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["install", "-r", filepath])

        file_size = os.path.getsize(filepath)
        timeout = self._calculate_timeout(file_size)

        success, output = self.adb_helper.run_command(args, timeout=timeout)
        if success and "Success" in output:
            return True, "安装成功"
        return False, output or "安装失败"

    def push_file(self, filepath: str, target_path: str, device_id: str = None) -> Tuple[bool, str]:
        """推送文件到设备"""
        if not os.path.exists(filepath):
            return False, "文件不存在"

        # 确保目标目录存在
        target_dir = os.path.dirname(target_path)
        if target_dir:
            mkdir_args = []
            if device_id:
                mkdir_args.extend(["-s", device_id])
            mkdir_args.extend(["shell", "mkdir", "-p", target_dir])
            self.adb_helper.run_command(mkdir_args)

        # 推送文件
        args = []
        if device_id:
            args.extend(["-s", device_id])
        args.extend(["push", filepath, target_path])

        file_size = os.path.getsize(filepath)
        timeout = self._calculate_timeout(file_size)

        success, output = self.adb_helper.run_command(args, timeout=timeout)
        if success:
            return True, f"已推送到 {target_path}"
        return False, output or "推送失败"

    def transfer_file(self, file_info: FileInfo, device_id: str = None) -> TransferResult:
        """传输单个文件（根据类型决定安装或推送）"""
        if file_info.file_type == FileType.APK:
            success, message = self.install_apk(file_info.path, device_id)
        else:
            success, message = self.push_file(file_info.path, file_info.target_path, device_id)

        return TransferResult(
            file_info=file_info,
            success=success,
            message=message,
            device_id=device_id or "default"
        )

    def transfer_files(
        self,
        file_infos: List[FileInfo],
        device_id: str = None,
        on_progress: Callable[[int, int, FileInfo, bool, str], None] = None
    ) -> List[TransferResult]:
        """
        批量传输文件

        Args:
            file_infos: 文件信息列表
            device_id: 设备ID
            on_progress: 进度回调 (当前索引, 总数, 文件信息, 是否成功, 消息)

        Returns:
            传输结果列表
        """
        results = []
        total = len(file_infos)

        for i, file_info in enumerate(file_infos):
            result = self.transfer_file(file_info, device_id)
            results.append(result)

            if on_progress:
                on_progress(i + 1, total, file_info, result.success, result.message)

        return results

    def transfer_to_multiple_devices(
        self,
        file_infos: List[FileInfo],
        device_ids: List[str],
        on_progress: Callable[[str, int, int, FileInfo, bool, str], None] = None
    ) -> dict:
        """
        向多个设备传输文件

        Args:
            file_infos: 文件信息列表
            device_ids: 设备ID列表
            on_progress: 进度回调 (设备ID, 当前索引, 总数, 文件信息, 是否成功, 消息)

        Returns:
            {device_id: [TransferResult, ...], ...}
        """
        all_results = {}

        for device_id in device_ids:
            device_results = []
            total = len(file_infos)

            for i, file_info in enumerate(file_infos):
                result = self.transfer_file(file_info, device_id)
                device_results.append(result)

                if on_progress:
                    on_progress(device_id, i + 1, total, file_info, result.success, result.message)

            all_results[device_id] = device_results

        return all_results

    def get_supported_extensions_display(self) -> str:
        """获取支持的文件类型说明"""
        return """支持的文件类型:
• APK: .apk, .xapk (安装应用)
• 视频: .mp4, .mkv, .avi, .mov, .wmv, .flv, .webm, .3gp
• 音频: .mp3, .wav, .flac, .aac, .ogg, .wma, .m4a
• 图片: .jpg, .png, .gif, .bmp, .webp
• 文档: .pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .txt
• 其他: .zip, .rar, .7z 等"""
