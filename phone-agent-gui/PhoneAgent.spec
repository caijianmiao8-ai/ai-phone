# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将 Phone Agent GUI 打包成 Windows 可执行文件

使用方法:
1. 先运行 python build.py 准备依赖
2. 或直接运行 pyinstaller PhoneAgent.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(SPEC))

block_cipher = None

# 收集数据文件
datas = [
    # ADB工具
    (os.path.join(BASE_DIR, 'adb'), 'adb'),
    # 配置目录
    (os.path.join(BASE_DIR, 'config'), 'config'),
    # 知识库数据
    (os.path.join(BASE_DIR, 'knowledge_base', 'data'), 'knowledge_base/data'),
]

# 如果本地有 phone_agent 模块，打包进去
phone_agent_path = os.path.join(BASE_DIR, 'phone_agent')
if os.path.exists(phone_agent_path):
    datas.append((phone_agent_path, 'phone_agent'))

# 收集 Gradio 及其依赖的数据文件
try:
    datas += collect_data_files('gradio')
except Exception:
    pass

try:
    datas += collect_data_files('gradio_client')
except Exception:
    pass

try:
    datas += collect_data_files('safehttpx')
except Exception:
    pass

# 隐藏导入
hiddenimports = [
    'gradio',
    'gradio.themes',
    'gradio_client',
    'PIL',
    'PIL.Image',
    'openai',
    'httpx',
    'safehttpx',
    'json',
    'threading',
    'dataclasses',
    'phone_agent',
    'phone_agent.agent',
    'phone_agent.model',
    'phone_agent.model.client',
    'phone_agent.actions',
    'phone_agent.actions.handler',
    'phone_agent.adb',
    'phone_agent.config',
]

# 收集 Gradio 子模块
try:
    hiddenimports += collect_submodules('gradio')
except Exception:
    pass

try:
    hiddenimports += collect_submodules('gradio_client')
except Exception:
    pass

a = Analysis(
    ['main.py'],
    pathex=[BASE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhoneAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 开启控制台以便查看日志，正式发布时改为 False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(BASE_DIR, 'resources', 'icon.ico') if os.path.exists(os.path.join(BASE_DIR, 'resources', 'icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhoneAgent',
)
