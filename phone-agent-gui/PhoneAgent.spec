# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于将 Phone Agent GUI 打包成 Windows 可执行文件
"""

import os
import sys

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(SPEC))
HOOKS_DIR = os.path.join(BASE_DIR, 'hooks')

block_cipher = None

# 收集数据文件
datas = []

# ADB工具
adb_dir = os.path.join(BASE_DIR, 'adb')
if os.path.exists(adb_dir):
    datas.append((adb_dir, 'adb'))

# 配置目录
config_dir = os.path.join(BASE_DIR, 'config')
if os.path.exists(config_dir):
    datas.append((config_dir, 'config'))

# 知识库数据
kb_data_dir = os.path.join(BASE_DIR, 'knowledge_base', 'data')
if os.path.exists(kb_data_dir):
    datas.append((kb_data_dir, 'knowledge_base/data'))

# 如果本地有 phone_agent 模块，打包进去
phone_agent_path = os.path.join(BASE_DIR, 'phone_agent')
if os.path.exists(phone_agent_path):
    datas.append((phone_agent_path, 'phone_agent'))

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

a = Analysis(
    ['main.py'],
    pathex=[BASE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[HOOKS_DIR],  # 使用自定义 hooks 目录
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
    console=True,  # 开启控制台以便查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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
