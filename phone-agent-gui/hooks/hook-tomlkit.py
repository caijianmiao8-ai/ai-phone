"""
PyInstaller hook for tomlkit package
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('tomlkit')
