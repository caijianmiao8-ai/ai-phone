# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(SPEC))
HOOKS_DIR = os.path.join(BASE_DIR, 'hooks')

block_cipher = None

# 收集数据文件
datas = []
binaries = []
hiddenimports = []

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

# 如果本地有 phone_agent 模块
phone_agent_path = os.path.join(BASE_DIR, 'phone_agent')
if os.path.exists(phone_agent_path):
    datas.append((phone_agent_path, 'phone_agent'))

# 收集 Gradio 及其所有依赖的数据文件
packages_to_collect = [
    'gradio',
    'gradio_client',
    'safehttpx',
    'groovy',
    'tomlkit',
    'huggingface_hub',
    'httpx',
    'anyio',
    'starlette',
    'fastapi',
    'uvicorn',
    'pydantic',
    'semantic_version',
    'aiofiles',
]

for pkg in packages_to_collect:
    try:
        pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hiddenimports
    except Exception as e:
        print(f"Warning: Could not collect {pkg}: {e}")

# 额外拷贝 Gradio 前端模板（避免丢失静态资源导致打包失败）
try:
    import gradio as _gradio

    gradio_base = os.path.dirname(_gradio.__file__)
    template_dir = os.path.join(gradio_base, "templates")
    if os.path.exists(template_dir):
        datas.append((template_dir, "gradio/templates"))
except Exception as e:
    print(f"Warning: Could not append gradio templates: {e}")

# 额外的隐藏导入
hiddenimports += [
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
    # core 模块
    'core',
    'core.agent_wrapper',
    'core.assistant_planner',
    'core.scheduler',
    'core.task_analyzer',
    'core.device_manager',
    'core.adb_helper',
    'core.device_registry',
    'core.file_transfer',
    'core.task_history',
    'core.task_plan',
    'core.task_queue',
    # ui 模块
    'ui',
    'ui.app',
    # knowledge_base 模块
    'knowledge_base',
    'knowledge_base.manager',
]

a = Analysis(
    ['main.py'],
    pathex=[BASE_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[HOOKS_DIR],
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
    console=True,
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
