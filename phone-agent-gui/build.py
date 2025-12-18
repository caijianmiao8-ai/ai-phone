#!/usr/bin/env python3
"""
打包脚本 - 将Phone Agent GUI打包成Windows可执行文件
"""
import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")
ADB_DIR = os.path.join(BASE_DIR, "adb")


def download_adb():
    """下载ADB工具"""
    if os.path.exists(os.path.join(ADB_DIR, "adb.exe")):
        print("ADB工具已存在，跳过下载")
        return True

    print("正在下载ADB工具...")
    adb_url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    zip_path = os.path.join(BASE_DIR, "platform-tools.zip")

    try:
        urllib.request.urlretrieve(adb_url, zip_path)

        print("正在解压ADB工具...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)

        # 移动文件到adb目录
        os.makedirs(ADB_DIR, exist_ok=True)
        platform_tools_dir = os.path.join(BASE_DIR, "platform-tools")

        for filename in ["adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"]:
            src = os.path.join(platform_tools_dir, filename)
            dst = os.path.join(ADB_DIR, filename)
            if os.path.exists(src):
                shutil.copy2(src, dst)

        # 清理
        shutil.rmtree(platform_tools_dir, ignore_errors=True)
        os.remove(zip_path)

        print("ADB工具下载完成")
        return True

    except Exception as e:
        print(f"下载ADB失败: {e}")
        print("请手动下载ADB工具并放置到 adb/ 目录")
        return False


def build_exe():
    """构建可执行文件"""
    print("开始构建可执行文件...")

    # PyInstaller参数
    pyinstaller_args = [
        "pyinstaller",
        "--name=PhoneAgent",
        "--onedir",  # 打包成目录而非单文件，便于包含ADB工具
        "--windowed",  # 无控制台窗口
        "--icon=resources/icon.ico",  # 图标 (如果有)
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        "--clean",
        # 添加数据文件
        f"--add-data=adb{os.pathsep}adb",
        f"--add-data=knowledge_base/data{os.pathsep}knowledge_base/data",
        f"--add-data=config{os.pathsep}config",
        # 隐藏导入
        "--hidden-import=gradio",
        "--hidden-import=PIL",
        "--hidden-import=openai",
        # 主文件
        "main.py",
    ]

    # 检查图标是否存在
    icon_path = os.path.join(BASE_DIR, "resources", "icon.ico")
    if not os.path.exists(icon_path):
        pyinstaller_args = [arg for arg in pyinstaller_args if "icon.ico" not in arg]

    try:
        subprocess.run(pyinstaller_args, check=True)
        print("构建完成!")

        # 复制原项目文件
        print("复制Phone Agent核心文件...")
        original_project = os.path.join(os.path.dirname(BASE_DIR), "Open-AutoGLM-main")
        if os.path.exists(original_project):
            dest_project = os.path.join(DIST_DIR, "PhoneAgent", "phone_agent_core")
            shutil.copytree(
                os.path.join(original_project, "phone_agent"),
                os.path.join(dest_project, "phone_agent"),
                dirs_exist_ok=True
            )

        print(f"\n构建输出目录: {os.path.join(DIST_DIR, 'PhoneAgent')}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"构建失败: {e}")
        return False


def create_readme():
    """创建使用说明"""
    readme_content = """# Phone Agent - AI手机助手

## 使用说明

### 1. 连接手机
- 在手机上开启「开发者选项」和「USB调试」
- 使用USB数据线连接手机和电脑
- 在手机上点击「允许USB调试」

### 2. 启动程序
- 双击 PhoneAgent.exe 启动程序
- 程序会自动打开浏览器访问界面

### 3. 配置API
- 进入「设置」页面
- 填写您的API Key（从智谱AI官网获取）
- 点击「测试API连接」确认配置正确

### 4. 执行任务
- 在「设备管理」中扫描并选择您的手机
- 在「任务执行」中输入您想要完成的任务
- 点击「开始执行」

### 5. 知识库（可选）
- 在「知识库」中可以添加自定义的操作指南
- 执行任务时勾选「启用知识库辅助」可以让AI更准确地完成任务

## 常见问题

Q: 扫描不到设备？
A: 请确保:
   1. 手机USB调试已开启
   2. 电脑已安装手机驱动
   3. USB线支持数据传输

Q: API连接失败？
A: 请检查:
   1. API Key是否正确
   2. 网络是否正常
   3. API地址是否正确

## 获取API Key
访问 https://open.bigmodel.cn 注册并获取API Key

"""
    with open(os.path.join(DIST_DIR, "PhoneAgent", "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(readme_content)


def main():
    """主函数"""
    print("=" * 50)
    print("  Phone Agent GUI 打包工具")
    print("=" * 50)
    print()

    # 下载ADB
    if not download_adb():
        print("警告: ADB工具未准备好，继续打包...")

    # 确保知识库数据目录存在
    kb_data_dir = os.path.join(BASE_DIR, "knowledge_base", "data")
    os.makedirs(kb_data_dir, exist_ok=True)

    # 创建空的知识库文件
    kb_file = os.path.join(kb_data_dir, "knowledge_base.json")
    if not os.path.exists(kb_file):
        with open(kb_file, "w", encoding="utf-8") as f:
            f.write("[]")

    # 构建
    if build_exe():
        create_readme()
        print()
        print("打包完成!")
        print(f"输出目录: {os.path.join(DIST_DIR, 'PhoneAgent')}")
        print()
        print("您可以将 PhoneAgent 文件夹压缩后分发给用户")


if __name__ == "__main__":
    main()
