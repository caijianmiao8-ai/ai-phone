"""
PyInstaller hook for huggingface_hub package
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('huggingface_hub')
