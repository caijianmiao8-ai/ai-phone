"""
智能任务执行引擎

实现任务分解、步骤执行、异常处理、状态追踪的完整流程
解决 AI 陷入死循环、不知道自己在做什么的问题
"""

import json
import re
import time
import base64
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple
from enum import Enum


# ==================== JSON 辅助函数 ====================

def clean_json_string(json_str: str) -> str:
    """清理 JSON 字符串（移除注释、尾随逗号等）"""
    # 移除 JavaScript 风格的注释
    json_str = re.sub(r'//.*$', '', json_str, flags=re.MULTILINE)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    # 移除尾随逗号（在数组或对象最后一个元素后）
    json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
    return json_str


def fix_common_json_issues(json_str: str) -> str:
    """修复常见的 JSON 问题（单引号、Python 风格的布尔值等）"""
    # 修复单引号
    json_str = json_str.replace("'", '"')
    # 修复 Python 风格的 True/False/None
    json_str = re.sub(r'\bTrue\b', 'true', json_str)
    json_str = re.sub(r'\bFalse\b', 'false', json_str)
    json_str = re.sub(r'\bNone\b', 'null', json_str)
    # 确保键名有引号（注意：这个正则可能过于激进，但通常有效）
    json_str = re.sub(r'(\w+)(?=\s*:)', r'"\1"', json_str)
    return json_str


def extract_json_from_response(response: str, required_field: Optional[str] = None) -> str:
    """
    从 AI 响应中提取 JSON（多策略）

    Args:
        response: AI 响应文本
        required_field: 可选的必需字段名（如 "steps"、"action"）

    Returns:
        提取的 JSON 字符串

    Raises:
        ValueError: 如果无法提取 JSON
    """
    # 策略1: 提取 ```json...``` 代码块
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json_match.group(1)

    # 策略2: 提取任何 {...} 结构
    json_match = re.search(r'\{[\s\S]*\}', response)
    if json_match:
        json_str = json_match.group(0)
        # 如果指定了必需字段，验证是否包含
        if required_field and f'"{required_field}"' in json_str:
            return json_str
        elif not required_field:
            return json_str

    # 策略3: 如果指定了必需字段，尝试查找包含该字段的 JSON 片段
    if required_field:
        field_match = re.search(
            rf'\{{[^}}]*"{required_field}"\s*:[\s\S]*?\}}',
            response,
            re.DOTALL
        )
        if field_match:
            return field_match.group(0)

    raise ValueError("无法从响应中提取 JSON")


# ==================== 数据结构定义 ====================

class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExceptionType(Enum):
    """异常类型"""
    AD_POPUP = "广告弹窗"
    LOGIN_REQUEST = "登录请求"
    PERMISSION_DIALOG = "权限弹窗"
    UPDATE_PROMPT = "更新提示"
    CAPTCHA = "验证码"
    NETWORK_ERROR = "网络错误"
    UNKNOWN_POPUP = "未知弹窗"
    NONE = "无异常"


@dataclass
class TaskStep:
    """任务步骤"""
    id: int
    goal: str                      # 步骤目标
    success_check: str             # 成功条件描述
    fallback: str = ""             # 备选策略
    max_retries: int = 3           # 最大重试次数
    is_critical: bool = True       # 是否关键步骤（失败则终止）
    timeout: int = 60              # 步骤超时（秒）
    status: StepStatus = StepStatus.PENDING


@dataclass
class TaskPlan:
    """任务计划"""
    understanding: str             # 任务理解
    steps: List[TaskStep]          # 步骤列表
    estimated_actions: int = 0     # 预估操作次数
    warnings: List[str] = field(default_factory=list)  # 可能的问题


@dataclass
class VerificationResult:
    """验证结果"""
    success: bool                  # 步骤是否完成
    unexpected_screen: ExceptionType = ExceptionType.NONE  # 意外界面类型
    wrong_path: bool = False       # 是否走错路径
    confidence: float = 0.0        # 判断置信度
    reason: str = ""               # 判断原因


@dataclass
class StepResult:
    """步骤执行结果"""
    success: bool
    message: str
    actions_taken: List[str] = field(default_factory=list)
    retries: int = 0
    exceptions_handled: List[str] = field(default_factory=list)


@dataclass
class ExecutionContext:
    """执行上下文"""
    task: str                      # 原始任务
    plan: Optional[TaskPlan] = None  # 任务计划
    current_step_index: int = 0    # 当前步骤索引
    start_time: float = 0          # 开始时间
    total_actions: int = 0         # 总操作次数
    completed_steps: List[int] = field(default_factory=list)
    skipped_steps: List[int] = field(default_factory=list)
    failed_steps: List[int] = field(default_factory=list)
    action_history: List[str] = field(default_factory=list)
    exception_history: List[str] = field(default_factory=list)

    def get_progress_summary(self) -> str:
        """获取进度摘要"""
        if not self.plan:
            return "任务未规划"

        total = len(self.plan.steps)
        completed = len(self.completed_steps)
        current = self.current_step_index + 1

        elapsed = time.time() - self.start_time if self.start_time else 0
        elapsed_str = f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"

        return f"步骤 {current}/{total} | 已完成 {completed} | 已用时 {elapsed_str}"

    def get_context_for_ai(self) -> str:
        """获取供 AI 使用的上下文"""
        if not self.plan:
            return ""

        current_step = self.plan.steps[self.current_step_index] if self.current_step_index < len(self.plan.steps) else None
        if not current_step:
            return ""

        # 已完成的步骤
        completed_str = ""
        for idx in self.completed_steps[-3:]:  # 最近3个
            if idx < len(self.plan.steps):
                completed_str += f"  ✓ {self.plan.steps[idx].goal}\n"

        # 后续步骤
        remaining_str = ""
        for i in range(self.current_step_index + 1, min(self.current_step_index + 3, len(self.plan.steps))):
            remaining_str += f"  → {self.plan.steps[i].goal}\n"

        elapsed = time.time() - self.start_time if self.start_time else 0

        context = f"""## 任务进度
任务: {self.plan.understanding}
当前: 步骤 {self.current_step_index + 1}/{len(self.plan.steps)} - {current_step.goal}
完成标志: {current_step.success_check}

## 已完成步骤
{completed_str if completed_str else "  (无)"}

## 后续步骤
{remaining_str if remaining_str else "  (最后一步)"}

## 执行统计
已用时: {int(elapsed)}秒 | 操作次数: {self.total_actions}
"""
        return context


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    message: str
    steps_completed: int = 0
    steps_skipped: int = 0
    steps_failed: int = 0
    total_actions: int = 0
    total_time: float = 0
    retries: int = 0
    exceptions_handled: List[str] = field(default_factory=list)
    execution_log: List[Dict] = field(default_factory=list)


# ==================== 任务规划器 ====================

class TaskPlanner:
    """
    任务规划器
    将用户任务分解为具体步骤
    """

    PLAN_PROMPT = """你是一个手机操作规划专家。请分析用户的任务，将其分解为具体的操作步骤。

## 用户任务
{task}

## 参考知识
{knowledge}

## ⚠️ 重要：必须严格按照JSON格式回复，不要添加任何额外的解释或文字！

## 输出格式示例
```json
{{
    "understanding": "在快手刷视频并点赞评论",
    "steps": [
        {{
            "id": 1,
            "goal": "打开快手应用",
            "success_check": "看到快手主界面，有视频流",
            "fallback": "如果找不到快手图标，尝试搜索",
            "is_critical": true
        }},
        {{
            "id": 2,
            "goal": "刷10个视频（上滑切换）",
            "success_check": "已经滑动10次，看过10个不同的视频",
            "fallback": "如果卡顿，重启应用",
            "is_critical": true
        }},
        {{
            "id": 3,
            "goal": "点赞5个视频",
            "success_check": "点赞图标变红，计数器显示已点赞5次",
            "fallback": "如果无法点赞，跳过该视频继续",
            "is_critical": false
        }},
        {{
            "id": 4,
            "goal": "评论3个视频",
            "success_check": "成功发送3条评论",
            "fallback": "如果评论失败，尝试简单文字",
            "is_critical": false
        }}
    ],
    "estimated_actions": 20,
    "warnings": ["可能需要登录", "部分视频可能无法评论"]
}}
```

## 规划要求
1. 步骤要具体、可执行，每个步骤对应一个明确的界面状态变化
2. success_check 要是具体可观察的界面特征
3. 考虑可能出现的弹窗、广告、登录等情况
4. is_critical=true 表示该步骤失败应终止任务
5. 步骤数量要合理（3-8步为宜）

现在请为上述任务生成JSON格式的计划："""

    def __init__(self, api_client: Callable[[str, Optional[str]], str]):
        """
        初始化任务规划器

        Args:
            api_client: AI API 调用函数 (prompt, image_base64) -> response
        """
        self.api_client = api_client

    def plan(self, task: str, screenshot_base64: Optional[str] = None,
             knowledge: str = "") -> TaskPlan:
        """
        规划任务

        Args:
            task: 用户任务描述
            screenshot_base64: 当前屏幕截图
            knowledge: 知识库参考内容

        Returns:
            TaskPlan 任务计划
        """
        prompt = self.PLAN_PROMPT.format(
            task=task,
            knowledge=knowledge if knowledge else "无相关知识库参考"
        )

        try:
            print(f"[DEBUG] TaskPlanner.plan: calling AI for task='{task}'")
            response = self.api_client(prompt, screenshot_base64)
            print(f"[DEBUG] TaskPlanner.plan: AI response length={len(response)}")
            print(f"[DEBUG] TaskPlanner.plan: AI response preview: {response[:500]}")

            plan = self._parse_plan_response(response)
            print(f"[DEBUG] TaskPlanner.plan: successfully parsed {len(plan.steps)} steps")
            return plan
        except Exception as e:
            # 解析失败时返回简单计划
            print(f"[DEBUG] TaskPlanner.plan: FAILED to parse, error={e}")
            print(f"[DEBUG] TaskPlanner.plan: falling back to single-step mode")
            return TaskPlan(
                understanding=task,
                steps=[TaskStep(
                    id=1,
                    goal=task,
                    success_check="任务完成",
                    is_critical=True
                )],
                warnings=[f"任务规划失败: {str(e)}，将使用简单模式执行"]
            )

    def _parse_plan_response(self, response: str) -> TaskPlan:
        """解析 AI 返回的计划（增强容错）"""
        # 提取 JSON（优先查找包含 "steps" 字段的）
        json_str = extract_json_from_response(response, required_field="steps")

        # 清理 JSON 字符串
        json_str = clean_json_string(json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] _parse_plan_response: JSON decode error - {e}")
            print(f"[DEBUG] _parse_plan_response: attempted to parse: {json_str[:200]}")
            # 尝试修复常见问题
            json_str = fix_common_json_issues(json_str)
            data = json.loads(json_str)  # 再次尝试

        steps = []
        for step_data in data.get("steps", []):
            steps.append(TaskStep(
                id=step_data.get("id", len(steps) + 1),
                goal=step_data.get("goal", ""),
                success_check=step_data.get("success_check", ""),
                fallback=step_data.get("fallback", ""),
                is_critical=step_data.get("is_critical", True),
                max_retries=step_data.get("max_retries", 3),
                timeout=step_data.get("timeout", 60)
            ))

        return TaskPlan(
            understanding=data.get("understanding", ""),
            steps=steps,
            estimated_actions=data.get("estimated_actions", len(steps) * 3),
            warnings=data.get("warnings", [])
        )


# ==================== 异常处理器 ====================

class ExceptionHandler:
    """
    异常处理器
    处理执行过程中的意外情况
    """

    DETECT_PROMPT = """请分析这张手机屏幕截图，判断是否出现了意外界面。

意外界面类型：
1. 广告弹窗 - 覆盖在主界面上的广告
2. 登录请求 - 要求登录或注册的弹窗
3. 权限弹窗 - 请求权限（如位置、通知等）
4. 更新提示 - 应用更新提醒
5. 验证码 - 需要人工验证的界面
6. 网络错误 - 网络连接失败提示
7. 未知弹窗 - 其他阻挡操作的弹窗
8. 无异常 - 正常界面，无弹窗

请用 JSON 格式回复：
```json
{{
    "exception_type": "上述类型之一",
    "confidence": 0-100,
    "dismiss_action": "建议的关闭操作，如：点击关闭、点击跳过、点击X等",
    "reason": "判断依据"
}}
```
"""

    # 各类异常的处理策略
    EXCEPTION_HANDLERS = {
        ExceptionType.AD_POPUP: [
            "点击右上角的关闭按钮",
            "点击跳过",
            "点击屏幕空白处",
            "按返回键"
        ],
        ExceptionType.LOGIN_REQUEST: [
            "点击取消",
            "点击稍后登录",
            "点击关闭",
            "按返回键"
        ],
        ExceptionType.PERMISSION_DIALOG: [
            "点击允许",  # 默认允许，可根据任务调整
            "点击拒绝"
        ],
        ExceptionType.UPDATE_PROMPT: [
            "点击稍后",
            "点击取消",
            "点击关闭"
        ],
        ExceptionType.NETWORK_ERROR: [
            "点击重试",
            "等待3秒后继续"
        ],
        ExceptionType.UNKNOWN_POPUP: [
            "点击关闭",
            "点击取消",
            "按返回键"
        ]
    }

    def __init__(self, api_client: Callable[[str, Optional[str]], str],
                 execute_func: Callable[[str], Tuple[bool, str]],
                 takeover_callback: Optional[Callable[[str], None]] = None):
        """
        初始化异常处理器

        Args:
            api_client: AI API 调用函数
            execute_func: 执行操作函数 (instruction) -> (success, message)
            takeover_callback: 用户接管回调
        """
        self.api_client = api_client
        self.execute_func = execute_func
        self.takeover_callback = takeover_callback

    def detect_exception(self, screenshot_base64: str) -> Tuple[ExceptionType, str]:
        """
        检测是否出现异常界面

        Args:
            screenshot_base64: 屏幕截图

        Returns:
            (异常类型, 建议的处理操作)
        """
        try:
            response = self.api_client(self.DETECT_PROMPT, screenshot_base64)

            # 解析响应
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group(0))
                exception_str = data.get("exception_type", "无异常")
                dismiss_action = data.get("dismiss_action", "")

                # 转换为枚举
                exception_type = ExceptionType.NONE
                for et in ExceptionType:
                    if et.value == exception_str:
                        exception_type = et
                        break

                return exception_type, dismiss_action

        except Exception:
            pass

        return ExceptionType.NONE, ""

    def handle_exception(self, exception_type: ExceptionType,
                        suggested_action: str = "") -> bool:
        """
        处理异常

        Args:
            exception_type: 异常类型
            suggested_action: AI 建议的操作

        Returns:
            是否成功处理
        """
        if exception_type == ExceptionType.NONE:
            return True

        if exception_type == ExceptionType.CAPTCHA:
            # 验证码需要用户接管
            if self.takeover_callback:
                self.takeover_callback("检测到验证码，请手动完成验证后继续")
            # 等待用户完成验证（最多等待30秒）
            time.sleep(30)
            return True

        # 获取处理策略
        actions = self.EXCEPTION_HANDLERS.get(exception_type, [])

        # 如果 AI 有建议，优先使用
        if suggested_action:
            actions = [suggested_action] + actions

        # 尝试执行处理操作
        for action in actions:
            if action.startswith("等待"):
                # 等待操作
                wait_match = re.search(r'(\d+)', action)
                if wait_match:
                    time.sleep(int(wait_match.group(1)))
                return True
            else:
                success, _ = self.execute_func(action)
                if success:
                    time.sleep(1)  # 等待界面响应
                    return True

        return False


# ==================== 步骤执行器 ====================

class StepExecutor:
    """
    步骤执行器
    执行单个步骤，包含重试和验证逻辑
    """

    ACTION_PROMPT = """## 任务上下文
{context}

## 当前目标
{goal}

## 完成标志
{success_check}

## ⚠️ 重要：必须严格按照 JSON 格式回复，不要添加任何额外的解释或文字！

## 请决定下一步操作
根据屏幕内容，执行什么操作可以达成当前步骤目标？

## 输出格式示例
```json
{{
    "thinking": "分析当前屏幕，说明为什么要这样操作",
    "action": "具体操作，如：点击搜索框、上滑、输入xxx、打开xxx",
    "wait_time": 2,
    "confidence": 85
}}
```

注意：
- action 字段必须是明确的操作指令，如"点击快手图标"、"向上滑动"、"输入文本xxx"
- wait_time 必须是数字（1-5之间）
- confidence 必须是数字（0-100之间）
- 只返回 JSON，不要添加额外的说明文字
"""

    VERIFY_PROMPT = """## 刚才的操作
{action}

## 预期结果
{expected}

## ⚠️ 重要：必须严格按照 JSON 格式回复，不要添加额外的解释文字！

## 请判断
观察当前屏幕，回答：
1. 预期结果是否已经出现？
2. 是否需要继续操作才能达成目标？
3. 是否走错了路径（进入了不相关的页面）？

## 输出格式示例
```json
{{
    "success": true,
    "need_more_action": false,
    "wrong_path": false,
    "confidence": 90,
    "reason": "屏幕显示快手主界面，视频正在播放"
}}
```

注意：
- success、need_more_action、wrong_path 必须是布尔值（true 或 false）
- confidence 必须是数字（0-100之间）
- 只返回 JSON，不要添加额外的说明文字
"""

    def __init__(self, api_client: Callable[[str, Optional[str]], str],
                 execute_func: Callable[[str], Tuple[bool, str]],
                 exception_handler: ExceptionHandler):
        """
        初始化步骤执行器

        Args:
            api_client: AI API 调用函数
            execute_func: 执行操作函数
            exception_handler: 异常处理器
        """
        self.api_client = api_client
        self.execute_func = execute_func
        self.exception_handler = exception_handler

    def execute_step(self, step: TaskStep, context: ExecutionContext,
                     capture_func: Callable[[], str]) -> StepResult:
        """
        执行单个步骤

        Args:
            step: 要执行的步骤
            context: 执行上下文
            capture_func: 截图函数

        Returns:
            StepResult 步骤结果
        """
        result = StepResult(success=False, message="")
        retry_count = 0
        actions_taken = []
        exceptions_handled = []
        exception_handle_count = 0  # 防止异常处理无限循环
        MAX_EXCEPTION_HANDLES = 5   # 最多处理5次异常
        step_start_time = time.time()  # 步骤开始时间

        step.status = StepStatus.IN_PROGRESS

        while retry_count < step.max_retries:
            # 检查步骤超时
            if time.time() - step_start_time > step.timeout:
                result.success = False
                result.message = f"步骤超时（{step.timeout}秒）"
                result.actions_taken = actions_taken
                result.retries = retry_count
                result.exceptions_handled = exceptions_handled
                step.status = StepStatus.FAILED
                return result
            # 1. 获取当前屏幕
            screenshot = capture_func()
            if not screenshot:
                retry_count += 1
                time.sleep(1)
                continue

            # 2. 检测异常界面（限制检测次数避免无限循环）
            if exception_handle_count < MAX_EXCEPTION_HANDLES:
                exception_type, dismiss_action = self.exception_handler.detect_exception(screenshot)
                if exception_type != ExceptionType.NONE:
                    handled = self.exception_handler.handle_exception(exception_type, dismiss_action)
                    if handled:
                        exceptions_handled.append(exception_type.value)
                        exception_handle_count += 1
                        # 处理后重新截图，不增加重试计数
                        continue
                    else:
                        retry_count += 1
                        continue

            # 3. 检查是否已经完成（执行前检查）
            pre_verify = self._verify_completion(screenshot, step, "检查当前状态")
            if pre_verify.success:
                result.success = True
                result.message = "步骤已完成"
                result.actions_taken = actions_taken
                result.exceptions_handled = exceptions_handled
                step.status = StepStatus.COMPLETED
                return result

            # 4. 决定操作
            print(f"[DEBUG] StepExecutor: calling _decide_action for step '{step.goal}'")
            action_info = self._decide_action(screenshot, step, context)
            if not action_info:
                print(f"[DEBUG] StepExecutor: _decide_action returned None, retrying")
                retry_count += 1
                continue

            action = action_info.get("action", "")
            wait_time = action_info.get("wait_time", 2)
            print(f"[DEBUG] StepExecutor: decided action='{action}', wait_time={wait_time}")

            # 5. 执行操作
            print(f"[DEBUG] StepExecutor: executing action '{action}'")
            success, message = self.execute_func(action)
            actions_taken.append(action)
            context.total_actions += 1
            context.action_history.append(action)
            print(f"[DEBUG] StepExecutor: action result - success={success}, message={message}")

            if not success:
                retry_count += 1
                continue

            # 6. 等待界面响应
            time.sleep(min(max(wait_time, 1), 5))

            # 7. 验证结果
            new_screenshot = capture_func()
            if not new_screenshot:
                retry_count += 1
                continue

            # 再次检测异常（同样受次数限制）
            if exception_handle_count < MAX_EXCEPTION_HANDLES:
                exception_type, dismiss_action = self.exception_handler.detect_exception(new_screenshot)
                if exception_type != ExceptionType.NONE:
                    handled = self.exception_handler.handle_exception(exception_type, dismiss_action)
                    if handled:
                        exceptions_handled.append(exception_type.value)
                        exception_handle_count += 1
                        new_screenshot = capture_func()
                        if not new_screenshot:
                            retry_count += 1
                            continue

            verify_result = self._verify_completion(new_screenshot, step, action)

            if verify_result.success:
                result.success = True
                result.message = "步骤完成"
                result.actions_taken = actions_taken
                result.retries = retry_count
                result.exceptions_handled = exceptions_handled
                step.status = StepStatus.COMPLETED
                return result

            if verify_result.wrong_path:
                # 走错路径，尝试返回
                self.execute_func("按返回键")
                time.sleep(1)

            # 8. 准备重试
            retry_count += 1
            if retry_count < step.max_retries:
                self._prepare_retry(step, retry_count, verify_result.reason)

        # 重试耗尽
        result.success = False
        result.message = f"步骤执行失败，已重试 {retry_count} 次"
        result.actions_taken = actions_taken
        result.retries = retry_count
        result.exceptions_handled = exceptions_handled
        step.status = StepStatus.FAILED
        return result

    def _decide_action(self, screenshot: str, step: TaskStep,
                       context: ExecutionContext) -> Optional[Dict]:
        """决定下一步操作（增强 JSON 解析）"""
        prompt = self.ACTION_PROMPT.format(
            context=context.get_context_for_ai(),
            goal=step.goal,
            success_check=step.success_check
        )

        try:
            print(f"[DEBUG] _decide_action: calling AI API...")
            response = self.api_client(prompt, screenshot)
            print(f"[DEBUG] _decide_action: AI returned {len(response)} chars")
            print(f"[DEBUG] _decide_action: response preview: {response[:200]}")

            # 提取 JSON（优先查找包含 "action" 字段的）
            json_str = extract_json_from_response(response, required_field="action")

            # 清理 JSON 字符串
            json_str = clean_json_string(json_str)

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"[DEBUG] _decide_action: JSON decode error - {e}")
                # 尝试修复常见问题
                json_str = fix_common_json_issues(json_str)
                data = json.loads(json_str)

            print(f"[DEBUG] _decide_action: parsed JSON successfully, action={data.get('action')}")
            return data

        except Exception as e:
            print(f"[DEBUG] _decide_action: failed to parse response - {e}")
            return None

    def _verify_completion(self, screenshot: str, step: TaskStep,
                          last_action: str) -> VerificationResult:
        """验证步骤是否完成（增强 JSON 解析）"""
        prompt = self.VERIFY_PROMPT.format(
            action=last_action,
            expected=step.success_check
        )

        try:
            response = self.api_client(prompt, screenshot)

            # 提取 JSON（优先查找包含 "success" 字段的）
            json_str = extract_json_from_response(response, required_field="success")
            json_str = clean_json_string(json_str)

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 尝试修复常见问题
                json_str = fix_common_json_issues(json_str)
                data = json.loads(json_str)

            # 安全解析 confidence
            confidence_raw = data.get("confidence", 0)
            try:
                confidence = float(confidence_raw) / 100
            except (TypeError, ValueError):
                confidence = 0.0

            return VerificationResult(
                success=bool(data.get("success", False)),
                wrong_path=bool(data.get("wrong_path", False)),
                confidence=confidence,
                reason=str(data.get("reason", ""))
            )
        except Exception as e:
            print(f"[DEBUG] _verify_completion: failed to parse response - {e}")
            return VerificationResult(success=False, reason="验证失败")

    def _prepare_retry(self, step: TaskStep, retry_num: int, reason: str):
        """准备重试"""
        if retry_num == 1:
            # 第一次重试：等待更长时间
            time.sleep(2)
        elif retry_num == 2:
            # 第二次重试：尝试滑动
            self.execute_func("向下滑动页面")
            time.sleep(1)
        elif retry_num >= 3 and step.fallback:
            # 使用 fallback 策略
            self.execute_func(step.fallback)
            time.sleep(1)


# ==================== 智能任务执行器 ====================

class SmartTaskExecutor:
    """
    智能任务执行器
    协调任务规划、步骤执行、异常处理的主控模块
    """

    def __init__(
        self,
        api_client: Callable[[str, Optional[str]], str],
        execute_func: Callable[[str], Tuple[bool, str]],
        capture_func: Callable[[], str],
        knowledge_search_func: Optional[Callable[[str], str]] = None,
        takeover_callback: Optional[Callable[[str], None]] = None,
        on_step_callback: Optional[Callable[[int, int, str, str], None]] = None,
        on_log_callback: Optional[Callable[[str], None]] = None,
        planner_api_client: Optional[Callable[[str, Optional[str]], str]] = None
    ):
        """
        初始化智能任务执行器

        Args:
            api_client: AI API 调用函数 (prompt, image_base64) -> response (用于执行)
            execute_func: 执行操作函数 (instruction) -> (success, message)
            capture_func: 截图函数 () -> base64_string
            knowledge_search_func: 知识库搜索函数 (query) -> knowledge_text
            takeover_callback: 用户接管回调
            on_step_callback: 步骤进度回调 (current, total, step_goal, status)
            on_log_callback: 日志回调
            planner_api_client: 任务规划专用 API 客户端（可选，默认使用 api_client）
        """
        self.api_client = api_client
        self.execute_func = execute_func
        self.capture_func = capture_func
        self.knowledge_search_func = knowledge_search_func
        self.takeover_callback = takeover_callback
        self.on_step_callback = on_step_callback
        self.on_log_callback = on_log_callback

        # 初始化子模块
        # 规划器使用更强的模型（如果提供）
        self.planner = TaskPlanner(planner_api_client or api_client)
        self.exception_handler = ExceptionHandler(
            api_client, execute_func, takeover_callback
        )
        self.step_executor = StepExecutor(
            api_client, execute_func, self.exception_handler
        )

        # 执行控制
        self._should_stop = False

    def _log(self, message: str):
        """记录日志"""
        if self.on_log_callback:
            self.on_log_callback(f"[SmartExecutor] {message}")

    def execute(self, task: str, max_steps: int = 50,
                timeout: float = 600) -> TaskResult:
        """
        执行任务

        Args:
            task: 任务描述
            max_steps: 最大步骤数
            timeout: 超时时间（秒）

        Returns:
            TaskResult 任务执行结果
        """
        self._should_stop = False
        start_time = time.time()

        # 初始化上下文
        context = ExecutionContext(
            task=task,
            start_time=start_time
        )

        execution_log = []

        try:
            # Phase 1: 任务规划
            self._log("开始任务规划...")
            screenshot = self.capture_func()
            if not screenshot:
                self._log("无法获取屏幕截图")
                return TaskResult(
                    success=False,
                    message="无法获取屏幕截图",
                    total_time=time.time() - start_time,
                    execution_log=execution_log
                )

            # 安全获取知识库内容
            knowledge = ""
            if self.knowledge_search_func:
                try:
                    knowledge = self.knowledge_search_func(task)
                except Exception as e:
                    self._log(f"知识库搜索失败: {str(e)}")

            plan = self.planner.plan(task, screenshot, knowledge)
            context.plan = plan

            self._log(f"任务理解: {plan.understanding}")
            self._log(f"计划步骤数: {len(plan.steps)}")

            if plan.warnings:
                for warning in plan.warnings:
                    self._log(f"警告: {warning}")

            # 记录计划
            execution_log.append({
                "phase": "planning",
                "understanding": plan.understanding,
                "steps": [{"id": s.id, "goal": s.goal} for s in plan.steps],
                "warnings": plan.warnings
            })

            # 检查空计划
            if not plan.steps:
                self._log("任务分解失败：没有生成任何步骤")
                return TaskResult(
                    success=False,
                    message="任务分解失败：没有生成任何步骤",
                    total_time=time.time() - start_time,
                    execution_log=execution_log
                )

            # Phase 2: 逐步执行
            for i, step in enumerate(plan.steps):
                if self._should_stop:
                    self._log("任务被手动停止")
                    break

                if time.time() - start_time > timeout:
                    self._log("任务超时")
                    break

                context.current_step_index = i
                self._log(f"执行步骤 {i + 1}/{len(plan.steps)}: {step.goal}")

                if self.on_step_callback:
                    self.on_step_callback(i + 1, len(plan.steps), step.goal, "executing")

                # 执行步骤
                step_result = self.step_executor.execute_step(
                    step, context, self.capture_func
                )

                # 记录结果
                execution_log.append({
                    "phase": "execution",
                    "step_id": step.id,
                    "goal": step.goal,
                    "success": step_result.success,
                    "actions": step_result.actions_taken,
                    "retries": step_result.retries,
                    "exceptions": step_result.exceptions_handled
                })

                # 更新上下文
                context.exception_history.extend(step_result.exceptions_handled)

                if step_result.success:
                    context.completed_steps.append(i)
                    self._log(f"步骤 {i + 1} 完成")
                    if self.on_step_callback:
                        self.on_step_callback(i + 1, len(plan.steps), step.goal, "completed")
                else:
                    if step.is_critical:
                        self._log(f"关键步骤 {i + 1} 失败，终止任务")
                        context.failed_steps.append(i)
                        if self.on_step_callback:
                            self.on_step_callback(i + 1, len(plan.steps), step.goal, "failed")

                        return TaskResult(
                            success=False,
                            message=f"关键步骤失败: {step.goal} - {step_result.message}",
                            steps_completed=len(context.completed_steps),
                            steps_skipped=len(context.skipped_steps),
                            steps_failed=len(context.failed_steps),
                            total_actions=context.total_actions,
                            total_time=time.time() - start_time,
                            exceptions_handled=context.exception_history,
                            execution_log=execution_log
                        )
                    else:
                        self._log(f"非关键步骤 {i + 1} 失败，跳过")
                        context.skipped_steps.append(i)
                        if self.on_step_callback:
                            self.on_step_callback(i + 1, len(plan.steps), step.goal, "skipped")

            # Phase 3: 返回结果
            total_time = time.time() - start_time
            success = len(context.failed_steps) == 0 and len(context.completed_steps) > 0

            return TaskResult(
                success=success,
                message=plan.understanding if success else "任务未完成",
                steps_completed=len(context.completed_steps),
                steps_skipped=len(context.skipped_steps),
                steps_failed=len(context.failed_steps),
                total_actions=context.total_actions,
                total_time=total_time,
                exceptions_handled=context.exception_history,
                execution_log=execution_log
            )

        except Exception as e:
            self._log(f"任务执行异常: {str(e)}")
            return TaskResult(
                success=False,
                message=f"执行异常: {str(e)}",
                total_time=time.time() - start_time,
                execution_log=execution_log
            )

    def execute_streaming(self, task: str, max_steps: int = 50,
                         timeout: float = 600) -> Generator[Dict, None, TaskResult]:
        """
        流式执行任务，逐步返回进度

        Args:
            task: 任务描述
            max_steps: 最大步骤数
            timeout: 超时时间

        Yields:
            进度信息字典

        Returns:
            TaskResult 任务执行结果
        """
        self._should_stop = False
        start_time = time.time()

        context = ExecutionContext(task=task, start_time=start_time)
        execution_log = []

        stopped_reason = None  # 记录停止原因

        try:
            # Phase 1: 规划
            yield {"phase": "planning", "message": "正在分析任务..."}

            screenshot = self.capture_func()
            if not screenshot:
                yield {"phase": "error", "success": False, "message": "无法获取屏幕截图"}
                return TaskResult(success=False, message="无法获取屏幕截图", total_time=time.time() - start_time)

            # 安全获取知识库内容
            knowledge = ""
            if self.knowledge_search_func:
                try:
                    knowledge = self.knowledge_search_func(task)
                except Exception as e:
                    self._log(f"知识库搜索失败: {str(e)}")

            plan = self.planner.plan(task, screenshot, knowledge)
            context.plan = plan

            yield {
                "phase": "planned",
                "understanding": plan.understanding,
                "total_steps": len(plan.steps),
                "steps": [{"id": s.id, "goal": s.goal} for s in plan.steps]
            }

            # 记录计划到 execution_log
            execution_log.append({
                "phase": "planning",
                "understanding": plan.understanding,
                "steps": [{"id": s.id, "goal": s.goal} for s in plan.steps],
                "warnings": plan.warnings
            })

            # 检查空计划
            if not plan.steps:
                yield {"phase": "error", "success": False, "message": "任务分解失败：没有生成任何步骤"}
                return TaskResult(success=False, message="任务分解失败：没有生成任何步骤",
                                total_time=time.time() - start_time, execution_log=execution_log)

            # Phase 2: 执行
            for i, step in enumerate(plan.steps):
                # 检查停止条件
                if self._should_stop:
                    stopped_reason = "stopped"
                    break
                if time.time() - start_time > timeout:
                    stopped_reason = "timeout"
                    break

                context.current_step_index = i

                yield {
                    "phase": "executing",
                    "step": i + 1,
                    "total": len(plan.steps),
                    "goal": step.goal,
                    "progress": context.get_progress_summary()
                }

                step_result = self.step_executor.execute_step(
                    step, context, self.capture_func
                )

                # 更新异常历史
                context.exception_history.extend(step_result.exceptions_handled)

                # 记录步骤执行结果到 execution_log
                execution_log.append({
                    "phase": "execution",
                    "step_id": step.id,
                    "goal": step.goal,
                    "success": step_result.success,
                    "actions": step_result.actions_taken,
                    "retries": step_result.retries,
                    "exceptions": step_result.exceptions_handled
                })

                if step_result.success:
                    context.completed_steps.append(i)
                    yield {
                        "phase": "step_completed",
                        "step": i + 1,
                        "goal": step.goal,
                        "actions": step_result.actions_taken
                    }
                else:
                    if step.is_critical:
                        context.failed_steps.append(i)
                        yield {
                            "phase": "step_failed",
                            "step": i + 1,
                            "goal": step.goal,
                            "reason": step_result.message,
                            "critical": True
                        }
                        break
                    else:
                        context.skipped_steps.append(i)
                        yield {
                            "phase": "step_skipped",
                            "step": i + 1,
                            "goal": step.goal,
                            "reason": step_result.message
                        }

            # Phase 3: 完成
            total_time = time.time() - start_time

            # 确定最终状态和消息
            if stopped_reason == "stopped":
                success = False
                message = "任务已手动停止"
                phase = "stopped"
            elif stopped_reason == "timeout":
                success = False
                message = f"任务超时（已用时 {int(total_time)} 秒）"
                phase = "timeout"
            elif len(context.failed_steps) > 0:
                success = False
                message = "任务执行失败"
                phase = "completed"
            elif len(context.completed_steps) > 0:
                success = True
                message = plan.understanding
                phase = "completed"
            else:
                success = False
                message = "任务未完成"
                phase = "completed"

            final_result = TaskResult(
                success=success,
                message=message,
                steps_completed=len(context.completed_steps),
                steps_skipped=len(context.skipped_steps),
                steps_failed=len(context.failed_steps),
                total_actions=context.total_actions,
                total_time=total_time,
                exceptions_handled=context.exception_history,
                execution_log=execution_log
            )

            # Yield final status before returning (so caller can capture it)
            yield {
                "phase": phase,
                "success": final_result.success,
                "message": final_result.message,
                "steps_completed": final_result.steps_completed,
                "steps_skipped": final_result.steps_skipped,
                "steps_failed": final_result.steps_failed,
                "total_actions": final_result.total_actions,
                "total_time": final_result.total_time
            }

            return final_result

        except Exception as e:
            error_result = TaskResult(
                success=False,
                message=f"执行异常: {str(e)}",
                total_time=time.time() - start_time
            )
            yield {
                "phase": "error",
                "success": False,
                "message": str(e)
            }
            return error_result

    def stop(self):
        """停止执行"""
        self._should_stop = True
