"""
设备注册表模块
管理设备的持久化存储、自定义名称等
"""
import json
import os
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict
from datetime import datetime

from config.settings import get_user_data_path


@dataclass
class SavedDevice:
    """已保存的设备信息"""
    device_id: str                    # 原始设备ID (如 192.168.1.100:5555 或 emulator-5554)
    custom_name: str = ""             # 用户自定义名称
    device_type: str = "usb"          # "usb" 或 "wifi"
    connection_address: str = ""      # WiFi连接地址 (IP:端口)
    brand: str = ""                   # 品牌
    model: str = ""                   # 型号
    android_version: str = ""         # Android版本
    sdk_version: str = ""             # SDK版本
    last_connected: str = ""          # 最后连接时间 ISO格式
    is_favorite: bool = False         # 是否收藏
    notes: str = ""                   # 备注信息

    @property
    def display_name(self) -> str:
        """显示名称：优先使用自定义名称"""
        if self.custom_name:
            return self.custom_name
        if self.model:
            return f"{self.brand} {self.model}".strip()
        return self.device_id

    @property
    def full_display_name(self) -> str:
        """完整显示名称：包含设备ID"""
        name = self.display_name
        if self.custom_name or self.model:
            return f"{name} ({self.device_id})"
        return name

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SavedDevice":
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def update_connection_time(self):
        """更新最后连接时间"""
        self.last_connected = datetime.now().isoformat()


class DeviceRegistry:
    """设备注册表 - 管理已保存设备的持久化"""

    def __init__(self):
        self._devices: Dict[str, SavedDevice] = {}
        self._config_path = self._get_config_path()
        self.load()

    def _get_config_path(self) -> str:
        """获取配置文件路径"""
        config_dir = os.path.join(get_user_data_path(), "config")
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "devices.json")

    def load(self):
        """从文件加载设备列表"""
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    devices_data = data.get("devices", [])
                    self._devices = {
                        d["device_id"]: SavedDevice.from_dict(d)
                        for d in devices_data
                    }
        except (json.JSONDecodeError, KeyError, TypeError):
            self._devices = {}

    def save(self):
        """保存设备列表到文件"""
        data = {
            "devices": [d.to_dict() for d in self._devices.values()],
            "updated_at": datetime.now().isoformat()
        }
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, device_id: str) -> Optional[SavedDevice]:
        """获取设备信息"""
        return self._devices.get(device_id)

    def get_all(self) -> List[SavedDevice]:
        """获取所有已保存设备"""
        return list(self._devices.values())

    def get_favorites(self) -> List[SavedDevice]:
        """获取收藏的设备"""
        return [d for d in self._devices.values() if d.is_favorite]

    def add_or_update(self, device: SavedDevice) -> SavedDevice:
        """添加或更新设备"""
        existing = self._devices.get(device.device_id)
        if existing:
            # 保留用户设置的字段
            if not device.custom_name and existing.custom_name:
                device.custom_name = existing.custom_name
            if not device.notes and existing.notes:
                device.notes = existing.notes
            if existing.is_favorite:
                device.is_favorite = True

        self._devices[device.device_id] = device
        self.save()
        return device

    def update_device_info(self, device_id: str, **kwargs) -> Optional[SavedDevice]:
        """更新设备信息字段"""
        device = self._devices.get(device_id)
        if not device:
            return None

        for key, value in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, value)

        self.save()
        return device

    def set_custom_name(self, device_id: str, name: str) -> bool:
        """设置设备自定义名称"""
        device = self._devices.get(device_id)
        if device:
            device.custom_name = name
            self.save()
            return True
        return False

    def set_favorite(self, device_id: str, is_favorite: bool) -> bool:
        """设置设备收藏状态"""
        device = self._devices.get(device_id)
        if device:
            device.is_favorite = is_favorite
            self.save()
            return True
        return False

    def set_notes(self, device_id: str, notes: str) -> bool:
        """设置设备备注"""
        device = self._devices.get(device_id)
        if device:
            device.notes = notes
            self.save()
            return True
        return False

    def remove(self, device_id: str) -> bool:
        """删除已保存的设备"""
        if device_id in self._devices:
            del self._devices[device_id]
            self.save()
            return True
        return False

    def get_by_name(self, name: str) -> Optional[SavedDevice]:
        """通过自定义名称查找设备"""
        for device in self._devices.values():
            if device.custom_name == name:
                return device
        return None

    def search(self, keyword: str) -> List[SavedDevice]:
        """搜索设备（按名称、ID、型号）"""
        keyword = keyword.lower()
        results = []
        for device in self._devices.values():
            if (keyword in device.device_id.lower() or
                keyword in device.custom_name.lower() or
                keyword in device.model.lower() or
                keyword in device.brand.lower()):
                results.append(device)
        return results

    def export_to_file(self, filepath: str):
        """导出设备列表"""
        data = {
            "devices": [d.to_dict() for d in self._devices.values()],
            "exported_at": datetime.now().isoformat()
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def import_from_file(self, filepath: str) -> int:
        """从文件导入设备列表，返回导入数量"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        count = 0
        for device_data in data.get("devices", []):
            device = SavedDevice.from_dict(device_data)
            self.add_or_update(device)
            count += 1

        return count
