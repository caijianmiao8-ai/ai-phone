#!/usr/bin/env python3
"""
Agent V2 运行入口

使用示例:
    python -m core.agent_v2.run "打开设置，查看 WLAN 列表"
    python -m core.agent_v2.run --verbose "打开微信"
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.agent_v2 import AgentV2, AgentConfig


def create_llm_client():
    """创建 LLM 客户端（使用现有的 ModelClient）"""
    try:
        from phone_agent.model import ModelClient, ModelConfig
        return ModelClient(ModelConfig())
    except ImportError:
        # 如果无法导入，使用 phone-agent-gui 中的配置
        pass

    # 备选：直接使用 OpenAI 兼容接口
    import os
    import requests

    class SimpleLLMClient:
        """简单的 LLM 客户端"""

        def __init__(self):
            self.api_url = os.getenv("LLM_API_URL", "http://localhost:8000/v1/chat/completions")
            self.api_key = os.getenv("LLM_API_KEY", "")
            self.model = os.getenv("LLM_MODEL", "gpt-4-vision-preview")

        def request(self, messages):
            """发送请求到 LLM"""
            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # 转换消息格式
            api_messages = []
            for msg in messages:
                if isinstance(msg.get("content"), list):
                    # 多模态消息
                    content = []
                    for item in msg["content"]:
                        if item["type"] == "text":
                            content.append({"type": "text", "text": item["text"]})
                        elif item["type"] == "image":
                            content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{item['source']['media_type']};base64,{item['source']['data']}"
                                }
                            })
                    api_messages.append({"role": msg["role"], "content": content})
                else:
                    api_messages.append(msg)

            response = requests.post(
                self.api_url,
                headers=headers,
                json={
                    "model": self.model,
                    "messages": api_messages,
                    "max_tokens": 1024,
                },
                timeout=60,
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # 返回一个简单的响应对象
            class Response:
                def __init__(self, text):
                    self.action = text

            return Response(content)

    return SimpleLLMClient()


def main():
    parser = argparse.ArgumentParser(description="Agent V2 - 闭环决策 Phone Agent")
    parser.add_argument("task", help="任务描述")
    parser.add_argument("--max-steps", type=int, default=50, help="最大步数 (默认: 50)")
    parser.add_argument("--verbose", "-v", action="store_true", help="输出详细日志")
    parser.add_argument("--output-dir", "-o", type=str, help="输出目录 (保存截图、日志)")

    args = parser.parse_args()

    # 配置
    config = AgentConfig(
        max_steps=args.max_steps,
        verbose=args.verbose,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )

    # 创建 LLM 客户端
    print("初始化 LLM 客户端...")
    llm_client = create_llm_client()

    # 创建 Agent
    print("初始化 Agent V2...")
    agent = AgentV2(llm_client=llm_client, config=config)

    # 执行任务
    print(f"\n开始执行任务: {args.task}\n")
    result = agent.run(args.task)

    # 输出结果
    print("\n" + "=" * 50)
    print("执行结果")
    print("=" * 50)
    print(f"任务: {result.task}")
    print(f"成功: {'是' if result.success else '否'}")
    print(f"消息: {result.message}")
    print(f"总步数: {result.total_steps}")
    print(f"耗时: {result.elapsed_seconds:.1f}秒")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
