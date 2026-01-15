"""测试 agent-v2 新增功能"""

import sys
sys.path.insert(0, '/home/user/ai-phone/Open-AutoGLM-main')

from phone_agent.agent import ExecutionContext, ActionRecord, compute_screen_hash


def test_loop_detection_no_change():
    """测试：连续无变化检测"""
    print("=" * 50)
    print("测试1: 连续屏幕无变化检测")
    print("=" * 50)

    ctx = ExecutionContext(task="测试任务", max_steps=50)

    # 模拟连续5次点击，屏幕都无变化
    for i in range(5):
        ctx.step_count = i + 1
        ctx.record_action(
            {"action": "Tap", "element": [500, 300]},
            "same_hash",  # 操作前
            "same_hash"   # 操作后相同 = 无变化
        )

    warning = ctx.detect_loop()
    print(f"操作历史: {len(ctx.action_history)} 步")
    print(f"警告信息: {warning}")
    print(f"干预操作: {ctx.intervention_action}")

    assert "无变化" in warning, "应该检测到无变化循环"
    assert ctx.intervention_action is not None, "应该触发自动干预"
    print("✓ 测试通过\n")


def test_loop_detection_repeat_action():
    """测试：重复相同操作检测"""
    print("=" * 50)
    print("测试2: 重复相同操作检测")
    print("=" * 50)

    ctx = ExecutionContext(task="测试任务", max_steps=50)

    # 模拟连续3次点击同一位置（但屏幕有变化）
    for i in range(3):
        ctx.step_count = i + 1
        ctx.record_action(
            {"action": "Tap", "element": [500, 300]},
            f"hash_{i}",
            f"hash_{i+1}"  # 每次都不同 = 有变化
        )

    warning = ctx.detect_loop()
    print(f"操作历史: {[f'{r.action_type}({r.action_params})' for r in ctx.action_history]}")
    print(f"警告信息: {warning}")

    assert "相同的 Tap" in warning, "应该检测到重复操作"
    print("✓ 测试通过\n")


def test_loop_detection_state_cycle():
    """测试：状态循环检测（回到之前的屏幕）"""
    print("=" * 50)
    print("测试3: 状态循环检测")
    print("=" * 50)

    ctx = ExecutionContext(task="测试任务", max_steps=50)

    # 模拟操作序列：不同操作导致屏幕变化，但最终回到起点
    # 使用不同操作避免触发"重复操作"检测
    actions_and_hashes = [
        ({"action": "Tap", "element": [100, 100]}, "hash_A", "hash_B"),
        ({"action": "Swipe", "start": [500, 800], "end": [500, 200]}, "hash_B", "hash_C"),
        ({"action": "Type", "text": "test"}, "hash_C", "hash_D"),
        ({"action": "Tap", "element": [200, 200]}, "hash_D", "hash_E"),
        ({"action": "Back"}, "hash_E", "hash_F"),
        ({"action": "Tap", "element": [300, 300]}, "hash_F", "hash_A"),  # 回到 hash_A
    ]

    for i, (action, h_before, h_after) in enumerate(actions_and_hashes):
        ctx.step_count = i + 1
        ctx.record_action(action, h_before, h_after)

    warning = ctx.detect_loop()
    hashes = ["hash_A"] + [h[2] for h in actions_and_hashes]
    print(f"屏幕状态序列: {hashes}")
    print(f"警告信息: {warning}")

    assert "状态与第" in warning, "应该检测到状态循环"
    print("✓ 测试通过\n")


def test_milestone_extraction():
    """测试：从 LLM 思考中提取里程碑"""
    print("=" * 50)
    print("测试4: 里程碑提取")
    print("=" * 50)

    ctx = ExecutionContext(task="打开淘宝购买iPhone", max_steps=50)

    # 模拟 LLM 的思考内容
    thinking1 = "分析当前屏幕，已经成功打开了淘宝应用 [里程碑:已打开淘宝] 现在需要搜索商品 [阶段:搜索商品]"
    ctx.extract_milestone_from_thinking(thinking1)
    print(f"思考1: {thinking1[:50]}...")
    print(f"  里程碑: {ctx.milestones}")
    print(f"  当前阶段: {ctx.current_stage}")

    thinking2 = "已经找到iPhone商品 [里程碑：已找到商品] 准备加入购物车 [阶段：添加购物车]"  # 中文冒号
    ctx.extract_milestone_from_thinking(thinking2)
    print(f"思考2: {thinking2[:50]}...")
    print(f"  里程碑: {ctx.milestones}")
    print(f"  当前阶段: {ctx.current_stage}")

    assert len(ctx.milestones) == 2, "应该有2个里程碑"
    assert ctx.current_stage == "添加购物车", "当前阶段应该更新"
    print("✓ 测试通过\n")


def test_task_state_building():
    """测试：构建结构化任务状态"""
    print("=" * 50)
    print("测试5: 结构化任务状态")
    print("=" * 50)

    ctx = ExecutionContext(task="打开淘宝搜索iPhone并加入购物车", max_steps=50)
    ctx.step_count = 15

    # 添加一些里程碑
    ctx.add_milestone("已打开淘宝")
    ctx.add_milestone("已搜索商品")
    ctx.set_current_stage("选择商品规格")

    # 添加操作历史
    ctx.record_action({"action": "Launch", "app": "taobao"}, "h1", "h2")
    ctx.record_action({"action": "Tap", "element": [500, 100]}, "h2", "h3")
    ctx.record_action({"action": "Type", "text": "iPhone"}, "h3", "h3")  # 无变化

    state = ctx.build_task_state()
    print("生成的任务状态:")
    print("-" * 40)
    print(state)
    print("-" * 40)

    assert "【任务目标】" in state
    assert "【已完成】" in state
    assert "【当前阶段】" in state
    assert "【最近操作】" in state
    print("✓ 测试通过\n")


def test_no_false_positive():
    """测试：正常操作不应触发误报"""
    print("=" * 50)
    print("测试6: 正常操作无误报")
    print("=" * 50)

    ctx = ExecutionContext(task="测试任务", max_steps=50)

    # 模拟正常的操作序列（不同操作，屏幕有变化）
    actions = [
        ({"action": "Launch", "app": "taobao"}, "h1", "h2"),
        ({"action": "Tap", "element": [500, 100]}, "h2", "h3"),
        ({"action": "Type", "text": "iPhone"}, "h3", "h4"),
        ({"action": "Tap", "element": [300, 500]}, "h4", "h5"),
        ({"action": "Swipe", "start": [500, 800], "end": [500, 200]}, "h5", "h6"),
    ]

    for i, (action, h_before, h_after) in enumerate(actions):
        ctx.step_count = i + 1
        ctx.record_action(action, h_before, h_after)

    warning = ctx.detect_loop()
    print(f"操作序列: {[a[0]['action'] for a in actions]}")
    print(f"警告信息: {repr(warning)}")

    assert warning == "", "正常操作不应触发警告"
    print("✓ 测试通过\n")


def test_knowledge_hints():
    """测试：知识库提取与注入"""
    print("=" * 50)
    print("测试7: 知识库提取与注入")
    print("=" * 50)

    ctx = ExecutionContext(task="刷抖音10分钟", max_steps=50)

    # 模拟知识库内容
    knowledge_content = """抖音使用操作指南：
1. 打开抖音APP
2. 上滑切换下一个视频
3. 双击屏幕点赞
4. 点击右侧评论图标发评论
5. 长按收藏视频
"""

    # 提取操作提示
    hints = ctx.extract_knowledge_hints(knowledge_content)
    print(f"知识库内容: {knowledge_content[:50]}...")
    print(f"提取的操作提示: {hints}")

    assert len(hints) > 0, "应该提取到操作提示"

    # 设置并验证任务状态包含提示
    ctx.knowledge_hints = hints
    ctx.step_count = 3
    state = ctx.build_task_state()
    print(f"任务状态包含操作提示: {'【操作提示】' in state}")

    assert "【操作提示】" in state, "任务状态应该包含操作提示"
    print("✓ 测试通过\n")


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Agent-V2 新功能测试")
    print("=" * 50 + "\n")

    test_loop_detection_no_change()
    test_loop_detection_repeat_action()
    test_loop_detection_state_cycle()
    test_milestone_extraction()
    test_task_state_building()
    test_no_false_positive()
    test_knowledge_hints()

    print("=" * 50)
    print("🎉 所有测试通过!")
    print("=" * 50)
