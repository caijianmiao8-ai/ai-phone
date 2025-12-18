"""
PyInstaller hook for gradio package
Collects all required data files and submodules
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files('gradio')
hiddenimports = collect_submodules('gradio')
