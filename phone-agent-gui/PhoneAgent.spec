# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将 Phone Agent GUI 打包成 Windows 可执行文件
"""

import os
import sys

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(SPEC))
ORIGINAL_PROJECT = os.path.join(os.path.dirname(BASE_DIR), "Open-AutoGLM-main")

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

# 如果原项目存在，也打包进去
if os.path.exists(ORIGINAL_PROJECT):
    datas.append(
        (os.path.join(ORIGINAL_PROJECT, 'phone_agent'), 'phone_agent')
    )

# 隐藏导入
hiddenimports = [
    'gradio',
    'gradio.themes',
    'PIL',
    'PIL.Image',
    'openai',
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

a = Analysis(
    ['main.py'],
    pathex=[BASE_DIR, ORIGINAL_PROJECT],
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
    console=False,  # 无控制台窗口
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
