"""
PyInstaller hook for gradio_client package
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files('gradio_client')
hiddenimports = collect_submodules('gradio_client')
