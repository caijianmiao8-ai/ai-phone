"""
PyInstaller hook for groovy package
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('groovy')
