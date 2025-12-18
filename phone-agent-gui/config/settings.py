"""
配置管理模块
管理应用设置，包括API配置、设备配置等
"""
import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Settings:
    """应用配置"""
    # 模型API配置
    api_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    api_key: str = ""
    model_name: str = "autoglm-phone-9b"
    max_tokens: int = 3000
    temperature: float = 0.1

    # 设备配置
    device_id: Optional[str] = None
    device_type: str = "adb"  # adb 或 hdc

    # 执行配置
    max_steps: int = 50
    action_delay: float = 1.0
    language: str = "cn"
    verbose: bool = True

    # 知识库配置
    knowledge_base_enabled: bool = True
    knowledge_base_path: str = ""

    # ADB配置
    adb_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        # 过滤掉不存在的字段
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


def get_config_path() -> str:
    """获取配置文件路径"""
    config_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config"
    )
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "settings.json")


def get_settings() -> Settings:
    """加载设置"""
    config_path = get_config_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return Settings.from_dict(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return Settings()


def save_settings(settings: Settings):
    """保存设置"""
    config_path = get_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
