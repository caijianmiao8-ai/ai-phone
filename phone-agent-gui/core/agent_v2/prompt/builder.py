"""提示词构建器 - 构建增强的 LLM 提示"""

from typing import Any, Dict, List, Optional

from ..types import Observation, VerifyResult


SYSTEM_PROMPT = """你是一个专业的手机自动化助手，负责操作 Android 手机来完成用户的任务。

## 你的能力

你可以看到手机屏幕截图和界面元素列表，然后决定下一步操作。

## 可用的操作

1. **tap** - 点击屏幕元素
   - element_index: 元素索引号（优先使用）
   - 或 x, y: 屏幕坐标

2. **long_press** - 长按元素
   - element_index: 元素索引号
   - 或 x, y: 屏幕坐标
   - duration_ms: 按压时长（毫秒，默认800）

3. **swipe** - 滑动屏幕
   - direction: up/down/left/right
   - distance: 滑动距离比例（0-1，默认0.3）

4. **type** - 输入文字
   - text: 要输入的文字

5. **back** - 返回上一页

6. **home** - 回到主屏幕

7. **wait** - 等待加载
   - duration_ms: 等待时长（毫秒，默认500）

8. **finish** - 任务完成
   - message: 完成说明

## 输出格式

你必须以 JSON 格式输出，包含以下字段：

```json
{
  "thinking": "你的思考过程：分析当前界面，判断任务进度，决定下一步操作",
  "action": "操作类型",
  "element_index": 元素索引（可选）,
  "x": x坐标（可选）,
  "y": y坐标（可选）,
  "direction": "滑动方向（可选）",
  "distance": 滑动距离（可选）,
  "text": "输入文字（可选）",
  "duration_ms": 时长（可选）,
  "message": "完成说明（可选）"
}
```

## 重要规则

1. **优先使用元素索引**：点击时优先使用 element_index，比坐标更准确
2. **仔细观察界面**：在操作前分析当前界面是否符合预期
3. **处理弹窗**：如果出现权限请求、更新提示等弹窗，先处理弹窗
4. **确认操作结果**：如果上一步操作未生效，考虑换一种方式
5. **避免重复失败**：如果连续失败，尝试不同的路径
6. **及时完成**：当任务目标达成时，使用 finish 结束任务

## 示例

点击元素：
```json
{"thinking": "需要点击设置按钮，界面中元素[5]是设置图标", "action": "tap", "element_index": 5}
```

滑动查找：
```json
{"thinking": "目标选项不在当前界面，需要向下滑动查找", "action": "swipe", "direction": "up", "distance": 0.4}
```

输入文字：
```json
{"thinking": "输入框已聚焦，输入搜索关键词", "action": "type", "text": "天气"}
```

任务完成：
```json
{"thinking": "已成功打开设置页面，任务完成", "action": "finish", "message": "已打开系统设置"}
```
"""


class PromptBuilder:
    """提示词构建器"""

    def __init__(self):
        self.system_prompt = SYSTEM_PROMPT

    def build_user_message(
        self,
        observation: Observation,
        task: str,
        context_summary: str,
        last_action_feedback: Optional[str] = None,
        is_first_step: bool = False,
    ) -> Dict[str, Any]:
        """
        构建用户消息（包含截图和界面信息）

        Args:
            observation: 当前观察
            task: 任务描述
            context_summary: 上下文摘要
            last_action_feedback: 上一步操作的反馈
            is_first_step: 是否是第一步

        Returns:
            包含 role, content 的消息字典
        """
        # 构建文本部分
        text_parts = []

        # 1. 第一步时显示任务
        if is_first_step:
            text_parts.append(f"## 任务\n\n{task}")

        # 2. 上下文摘要
        if context_summary:
            text_parts.append(f"## 执行状态\n\n{context_summary}")

        # 3. 上一步反馈
        if last_action_feedback:
            text_parts.append(f"## 上一步结果\n\n{last_action_feedback}")

        # 4. 当前界面信息
        text_parts.append(self._build_screen_info(observation))

        # 5. 界面元素列表
        text_parts.append(self._build_ui_elements(observation))

        text_content = "\n\n".join(text_parts)

        # 构建消息
        return {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": observation.screenshot_base64,
                    },
                },
                {
                    "type": "text",
                    "text": text_content,
                },
            ],
        }

    def build_system_message(self) -> Dict[str, Any]:
        """构建系统消息"""
        return {
            "role": "user",  # Claude API 使用 user 发送系统提示
            "content": self.system_prompt,
        }

    def _build_screen_info(self, observation: Observation) -> str:
        """构建屏幕基础信息"""
        lines = ["## 当前屏幕"]

        # 应用信息
        if observation.package:
            app_name = observation.package.split(".")[-1]
            lines.append(f"- 应用: {app_name} ({observation.package})")

        if observation.activity:
            activity_name = observation.activity.split(".")[-1]
            lines.append(f"- 页面: {activity_name}")

        # 键盘状态
        if observation.is_keyboard_shown:
            lines.append("- 键盘: 已弹出（可以输入文字）")

        # 屏幕尺寸
        lines.append(f"- 分辨率: {observation.screen_width}x{observation.screen_height}")

        return "\n".join(lines)

    def _build_ui_elements(self, observation: Observation) -> str:
        """构建 UI 元素列表"""
        ui_desc = observation.get_ui_description(max_elements=50)
        return f"## 界面元素\n\n以下是可交互的界面元素（[索引] 文本/描述 属性）:\n\n{ui_desc}"

    def build_action_feedback(self, verify_result: VerifyResult) -> str:
        """构建行动反馈"""
        return verify_result.to_feedback()


def parse_llm_response(response_text: str) -> Dict[str, Any]:
    """
    解析 LLM 的 JSON 响应

    Args:
        response_text: LLM 返回的文本

    Returns:
        解析后的字典
    """
    import json
    import re

    # 尝试直接解析
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown 代码块中提取
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试查找 JSON 对象
    json_match = re.search(r"\{[^{}]*\}", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # 解析失败，返回默认的等待操作
    return {
        "thinking": f"无法解析响应: {response_text[:100]}",
        "action": "wait",
        "duration_ms": 1000,
    }
