"""行动验证器 - 检测行动是否生效"""

from typing import List, Set

from ..types import Action, ActionType, Observation, VerifyResult


class Verifier:
    """
    行动验证器

    核心职责：
    1. 比较执行前后的观察，判断行动是否生效
    2. 生成人类可读的变化描述，反馈给 LLM
    """

    # 常见弹窗关键词
    POPUP_KEYWORDS = [
        "允许", "Allow", "拒绝", "Deny",
        "同意", "Agree", "取消", "Cancel",
        "确定", "OK", "确认", "Confirm",
        "稍后", "Later", "以后再说",
        "跳过", "Skip", "关闭", "Close",
        "更新", "Update", "升级",
        "权限", "Permission",
    ]

    # 常见错误状态关键词
    ERROR_KEYWORDS = [
        "网络错误", "Network Error",
        "连接失败", "Connection Failed",
        "加载失败", "Load Failed",
        "请重试", "Please Retry",
        "登录", "Sign in", "Login",
        "重新登录", "Re-login",
    ]

    def verify(
        self,
        before: Observation,
        after: Observation,
        action: Action,
    ) -> VerifyResult:
        """
        验证行动效果

        Args:
            before: 执行前的观察
            after: 执行后的观察
            action: 执行的行动

        Returns:
            VerifyResult 包含变化信息和反馈
        """
        changes = []

        # 1. 检测屏幕内容变化
        screen_changed = before.screen_hash != after.screen_hash
        if screen_changed:
            changes.append("screen_changed")

        # 2. 检测 Activity 变化
        activity_changed = before.activity != after.activity
        if activity_changed:
            changes.append("activity_changed")

        # 3. 检测 Package 变化（跳转到其他应用）
        package_changed = before.package != after.package
        if package_changed:
            changes.append("package_changed")

        # 4. 检测键盘状态变化
        keyboard_shown = not before.is_keyboard_shown and after.is_keyboard_shown
        keyboard_hidden = before.is_keyboard_shown and not after.is_keyboard_shown
        if keyboard_shown:
            changes.append("keyboard_shown")
        if keyboard_hidden:
            changes.append("keyboard_hidden")

        # 5. 检测弹窗出现
        popup_detected = self._detect_popup(after)
        if popup_detected:
            changes.append("popup_detected")

        # 6. 检测错误状态
        error_detected = self._detect_error(after)
        if error_detected:
            changes.append("error_detected")

        # 7. 构建变化描述
        has_change = len(changes) > 0
        change_type = self._classify_change(changes, action)
        details = self._build_details(before, after, changes, action)

        return VerifyResult(
            changed=has_change,
            change_type=change_type,
            details=details,
        )

    def _detect_popup(self, observation: Observation) -> bool:
        """检测是否有弹窗"""
        for elem in observation.ui_elements:
            text = elem.text + " " + elem.content_desc
            for keyword in self.POPUP_KEYWORDS:
                if keyword in text:
                    return True
        return False

    def _detect_error(self, observation: Observation) -> bool:
        """检测是否有错误状态"""
        for elem in observation.ui_elements:
            text = elem.text + " " + elem.content_desc
            for keyword in self.ERROR_KEYWORDS:
                if keyword in text:
                    return True
        return False

    def _classify_change(self, changes: List[str], action: Action) -> str:
        """对变化进行分类"""
        if not changes:
            return "none"

        # 优先级分类
        if "error_detected" in changes:
            return "error"

        if "popup_detected" in changes:
            return "popup"

        if "package_changed" in changes:
            return "app_switch"

        if "activity_changed" in changes:
            return "navigation"

        if "keyboard_shown" in changes:
            return "keyboard_shown"

        if "keyboard_hidden" in changes:
            return "keyboard_hidden"

        if "screen_changed" in changes:
            return "screen_update"

        return "unknown"

    def _build_details(
        self,
        before: Observation,
        after: Observation,
        changes: List[str],
        action: Action,
    ) -> str:
        """构建详细的变化描述"""
        if not changes:
            return self._build_no_change_feedback(action)

        parts = []

        if "package_changed" in changes:
            parts.append(f"应用切换: {before.package} -> {after.package}")

        if "activity_changed" in changes:
            # 简化 activity 名称
            before_act = before.activity.split(".")[-1] if before.activity else ""
            after_act = after.activity.split(".")[-1] if after.activity else ""
            parts.append(f"页面跳转: {before_act} -> {after_act}")

        if "keyboard_shown" in changes:
            parts.append("键盘已弹出，可以输入文字")

        if "keyboard_hidden" in changes:
            parts.append("键盘已收起")

        if "popup_detected" in changes:
            popup_text = self._find_popup_text(after)
            parts.append(f"检测到弹窗: {popup_text}")

        if "error_detected" in changes:
            error_text = self._find_error_text(after)
            parts.append(f"检测到错误: {error_text}")

        if "screen_changed" in changes and not parts:
            # 只有屏幕变化，没有其他具体变化
            new_elements = self._find_new_elements(before, after)
            if new_elements:
                parts.append(f"界面更新，新出现: {', '.join(new_elements[:3])}")
            else:
                parts.append("界面内容已更新")

        return "; ".join(parts) if parts else "界面已变化"

    def _build_no_change_feedback(self, action: Action) -> str:
        """构建无变化时的反馈"""
        action_type = action.action_type

        if action_type == ActionType.TAP:
            return "点击后屏幕无变化，可能: 1)目标不可点击 2)需要等待加载 3)点击位置不准确"

        if action_type == ActionType.SWIPE:
            return "滑动后屏幕无变化，可能已到达边界或页面不可滚动"

        if action_type == ActionType.TYPE:
            return "输入后屏幕无变化，可能输入框未聚焦或不接受输入"

        if action_type == ActionType.WAIT:
            return "等待结束，屏幕无变化"

        return "操作后屏幕无变化"

    def _find_popup_text(self, observation: Observation) -> str:
        """查找弹窗中的关键文本"""
        keywords_found = []
        for elem in observation.ui_elements:
            text = elem.text or elem.content_desc
            for keyword in self.POPUP_KEYWORDS:
                if keyword in text and keyword not in keywords_found:
                    keywords_found.append(keyword)
        return ", ".join(keywords_found[:3]) if keywords_found else "未知弹窗"

    def _find_error_text(self, observation: Observation) -> str:
        """查找错误相关的文本"""
        for elem in observation.ui_elements:
            text = elem.text or elem.content_desc
            for keyword in self.ERROR_KEYWORDS:
                if keyword in text:
                    return text[:50]  # 截取前50字符
        return "未知错误"

    def _find_new_elements(self, before: Observation, after: Observation) -> List[str]:
        """查找新出现的 UI 元素"""
        before_texts: Set[str] = set()
        for elem in before.ui_elements:
            if elem.text:
                before_texts.add(elem.text)

        new_elements = []
        for elem in after.ui_elements:
            if elem.text and elem.text not in before_texts:
                if len(elem.text) < 30:  # 只保留较短的文本
                    new_elements.append(elem.text)

        return new_elements[:5]
