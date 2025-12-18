#!/usr/bin/env python3
"""
Phone Agent GUI - AI手机助手
主入口文件
"""
import os
import sys

# 设置项目路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 添加原项目路径
ORIGINAL_PROJECT_PATH = os.path.join(
    os.path.dirname(BASE_DIR),
    "Open-AutoGLM-main"
)
if os.path.exists(ORIGINAL_PROJECT_PATH):
    sys.path.insert(0, ORIGINAL_PROJECT_PATH)


def setup_environment():
    """设置环境"""
    from core.adb_helper import ADBHelper

    # 初始化ADB
    adb_helper = ADBHelper()
    adb_helper.setup_environment()

    # 启动ADB服务
    if adb_helper.is_available():
        adb_helper.start_server()
        print(f"ADB: {adb_helper.get_version()}")
    else:
        print("警告: ADB不可用，请检查ADB工具是否正确配置")

    # 初始化知识库默认模板
    from knowledge_base.manager import KnowledgeManager
    km = KnowledgeManager()
    if not km.get_all():
        print("正在创建默认知识库模板...")
        km.create_default_templates()
        print(f"已创建 {len(km.get_all())} 条默认知识")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Phone Agent GUI - AI手机助手")
    parser.add_argument(
        "--share",
        action="store_true",
        help="创建公共分享链接",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
        help="服务端口号 (默认: 7860)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="不自动打开浏览器",
    )

    args = parser.parse_args()

    print("=" * 50)
    print("  Phone Agent GUI - AI手机助手")
    print("=" * 50)
    print()

    # 设置环境
    setup_environment()

    print()
    print(f"启动服务...")
    print(f"访问地址: http://localhost:{args.port}")
    print()

    # 启动UI
    from ui.app import create_app

    app = create_app()
    app.launch(
        share=args.share,
        server_port=args.port,
        inbrowser=not args.no_browser,
        show_error=True,
    )


if __name__ == "__main__":
    main()
