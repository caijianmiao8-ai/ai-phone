"""
PyInstaller hook for safehttpx package
Collects the version.txt file that is required at runtime
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('safehttpx')
