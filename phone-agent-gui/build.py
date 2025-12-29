#!/usr/bin/env python3
"""
打包脚本 - 将Phone Agent GUI打包成Windows可执行文件
会自动集成 Open-AutoGLM-main 的核心模块
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
SCRCPY_DIR = os.path.join(BASE_DIR, "scrcpy")

# 原项目路径
ORIGINAL_PROJECT = os.path.join(os.path.dirname(BASE_DIR), "Open-AutoGLM-main")


def download_adb():
    """下载ADB工具"""
    if os.path.exists(os.path.join(ADB_DIR, "adb.exe")):
        print("✓ ADB工具已存在")
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

        print("✓ ADB工具下载完成")
        return True

    except Exception as e:
        print(f"✗ 下载ADB失败: {e}")
        print("  请手动下载ADB工具并放置到 adb/ 目录")
        return False


def download_scrcpy():
    """下载scrcpy投屏工具"""
    if os.path.exists(os.path.join(SCRCPY_DIR, "scrcpy.exe")):
        print("✓ scrcpy工具已存在")
        return True

    print("正在下载scrcpy投屏工具...")
    # scrcpy 官方 Windows 64位版本
    scrcpy_url = "https://github.com/Genymobile/scrcpy/releases/download/v3.1/scrcpy-win64-v3.1.zip"
    zip_path = os.path.join(BASE_DIR, "scrcpy-win64.zip")

    try:
        # 下载
        print(f"  下载地址: {scrcpy_url}")
        urllib.request.urlretrieve(scrcpy_url, zip_path)

        print("正在解压scrcpy工具...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)

        # scrcpy 解压后目录名类似 scrcpy-win64-v3.1
        extracted_dir = None
        for name in os.listdir(BASE_DIR):
            if name.startswith("scrcpy-win64"):
                extracted_dir = os.path.join(BASE_DIR, name)
                break

        if extracted_dir and os.path.exists(extracted_dir):
            # 移动到 scrcpy 目录
            if os.path.exists(SCRCPY_DIR):
                shutil.rmtree(SCRCPY_DIR)
            shutil.move(extracted_dir, SCRCPY_DIR)

        # 清理
        os.remove(zip_path)

        print("✓ scrcpy工具下载完成")
        return True

    except Exception as e:
        print(f"✗ 下载scrcpy失败: {e}")
        print("  请手动下载scrcpy并放置到 scrcpy/ 目录")
        print("  下载地址: https://github.com/Genymobile/scrcpy/releases")
        return False


def copy_phone_agent():
    """复制原项目的 phone_agent 模块到当前目录"""
    src_path = os.path.join(ORIGINAL_PROJECT, "phone_agent")
    dst_path = os.path.join(BASE_DIR, "phone_agent")

    if not os.path.exists(ORIGINAL_PROJECT):
        print(f"✗ 未找到原项目: {ORIGINAL_PROJECT}")
        print("  请确保 Open-AutoGLM-main 文件夹与 phone-agent-gui 在同一目录下")
        return False

    if not os.path.exists(src_path):
        print(f"✗ 未找到 phone_agent 模块: {src_path}")
        return False

    # 删除旧的复制
    if os.path.exists(dst_path):
        shutil.rmtree(dst_path)

    # 复制模块
    print(f"正在复制 phone_agent 模块...")
    shutil.copytree(src_path, dst_path)
    print("✓ phone_agent 模块复制完成")
    return True


def build_exe():
    """构建可执行文件"""
    print("开始构建可执行文件...")

    # 使用 spec 文件打包
    spec_file = os.path.join(BASE_DIR, "PhoneAgent.spec")

    try:
        subprocess.run(
            ["pyinstaller", "--clean", "--noconfirm", spec_file],
            check=True,
            cwd=BASE_DIR
        )
        print("✓ 构建完成!")
        return True

    except subprocess.CalledProcessError as e:
        print(f"✗ 构建失败: {e}")
        return False
    except FileNotFoundError:
        print("✗ 未找到 pyinstaller，请先安装: pip install pyinstaller")
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
- 默认地址: http://localhost:7860

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
   4. 在手机上点击了「允许USB调试」

Q: API连接失败？
A: 请检查:
   1. API Key是否正确
   2. 网络是否正常
   3. API地址是否正确

Q: 程序闪退？
A: 请尝试:
   1. 以管理员身份运行
   2. 检查是否有杀毒软件拦截
   3. 查看同目录下的日志文件

## 获取API Key
访问 https://open.bigmodel.cn 注册并获取API Key

## 技术支持
如有问题，请联系开发者
"""
    output_dir = os.path.join(DIST_DIR, "PhoneAgent")
    if os.path.exists(output_dir):
        with open(os.path.join(output_dir, "使用说明.txt"), "w", encoding="utf-8") as f:
            f.write(readme_content)
        print("✓ 使用说明已创建")


def main():
    """主函数"""
    print("=" * 50)
    print("  Phone Agent GUI 打包工具")
    print("=" * 50)
    print()

    # 步骤1: 复制 phone_agent 模块
    print("[1/5] 集成 phone_agent 模块...")
    if not copy_phone_agent():
        print("\n打包失败: 无法集成 phone_agent 模块")
        sys.exit(1)

    # 步骤2: 下载ADB
    print("\n[2/5] 准备 ADB 工具...")
    if not download_adb():
        print("警告: ADB工具未准备好，继续打包...")

    # 步骤3: 下载scrcpy
    print("\n[3/5] 准备 scrcpy 投屏工具...")
    if not download_scrcpy():
        print("警告: scrcpy工具未准备好，继续打包...")

    # 步骤4: 确保必要目录存在
    print("\n[4/5] 准备资源文件...")

    # 知识库数据目录
    kb_data_dir = os.path.join(BASE_DIR, "knowledge_base", "data")
    os.makedirs(kb_data_dir, exist_ok=True)
    kb_file = os.path.join(kb_data_dir, "knowledge_base.json")
    if not os.path.exists(kb_file):
        with open(kb_file, "w", encoding="utf-8") as f:
            f.write("[]")

    # config目录
    config_dir = os.path.join(BASE_DIR, "config")
    os.makedirs(config_dir, exist_ok=True)

    print("✓ 资源文件准备完成")

    # 步骤5: 构建
    print("\n[5/5] 构建可执行文件...")
    if build_exe():
        create_readme()
        print()
        print("=" * 50)
        print("  打包完成!")
        print(f"  输出目录: {os.path.join(DIST_DIR, 'PhoneAgent')}")
        print("=" * 50)
        print()
        print("您可以将 PhoneAgent 文件夹压缩后分发给用户")
    else:
        print()
        print("打包失败，请检查错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
