# Dify 工作流集成指南

本指南详细说明如何将 Dify 工作流与 PhoneAgent 系统集成，实现混合架构的智能手机控制。

## 架构概述

```
┌─────────────────────────────────────────────────────────────────────┐
│                          用户界面层                                  │
│                    (Gradio Web Interface)                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                ▼                               ▼
┌──────────────────────────┐     ┌──────────────────────────────────┐
│     任务路由器            │     │        API 服务器                 │
│  (TaskRouter)            │     │   (PhoneAgentAPIServer)          │
│                          │     │   http://localhost:8765          │
│  ┌────────────────────┐  │     │                                  │
│  │ 简单任务 → 直接执行 │  │     │   /execute    - 单步执行         │
│  │ 复杂任务 → Dify    │  │     │   /screenshot - 获取截图         │
│  └────────────────────┘  │     │   /analyze    - 屏幕分析         │
└──────────────────────────┘     │   /tasks      - 异步任务         │
                │                └──────────────────────────────────┘
                │                                ▲
                ▼                                │
┌──────────────────────────────────────────────────────────────────────┐
│                         Dify 工作流引擎                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │  开始节点   │→ │  分析节点   │→ │  循环节点   │→ │  结束节点   │ │
│  │  接收任务   │  │  判断状态   │  │  执行操作   │  │  返回结果   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       PhoneAgent 执行层                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  VLM 视觉理解 → 动作决策 → ADB 执行 → 结果反馈              │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 启动 API 服务器

在 `phone-agent-gui` 启动时会自动启动 API 服务器（端口 8765）。

手动启动方式：

```python
from core.api_server import init_api_server
from core.agent_wrapper import AgentWrapper
from core.device_manager import DeviceManager

# 初始化组件
device_manager = DeviceManager()
agent_wrapper = AgentWrapper(
    api_base_url="https://your-api.com/v1",
    api_key="your-api-key"
)

# 启动 API 服务器
api_server = init_api_server(
    agent_wrapper=agent_wrapper,
    device_manager=device_manager,
    port=8765
)
```

### 2. 在 Dify 中配置 HTTP 请求节点

在 Dify 工作流中添加 HTTP 请求节点，配置如下：

**获取截图：**
```
POST http://your-server:8765/screenshot
Content-Type: application/json

{
    "device_id": "{{device_id}}"
}
```

**执行操作：**
```
POST http://your-server:8765/execute
Content-Type: application/json

{
    "device_id": "{{device_id}}",
    "instruction": "{{instruction}}",
    "wait_after": 2
}
```

**分析屏幕：**
```
POST http://your-server:8765/analyze
Content-Type: application/json

{
    "screenshot": "{{screenshot_base64}}",
    "question": "{{question}}"
}
```

## API 接口详细说明

### GET /health
健康检查

**响应：**
```json
{"status": "ok", "timestamp": 1234567890}
```

### GET /devices
获取设备列表

**响应：**
```json
{
    "success": true,
    "devices": [
        {
            "id": "192.168.1.100:5555",
            "model": "Redmi Note 12",
            "status": "device",
            "connected": true
        }
    ]
}
```

### POST /screenshot
获取屏幕截图

**请求：**
```json
{
    "device_id": "192.168.1.100:5555"
}
```

**响应：**
```json
{
    "success": true,
    "screenshot": "base64_encoded_image...",
    "width": 1080,
    "height": 2400,
    "message": "OK"
}
```

### POST /execute
执行单步指令

**请求：**
```json
{
    "device_id": "192.168.1.100:5555",
    "instruction": "点击屏幕中央的播放按钮",
    "wait_after": 2.0,
    "timeout": 30.0
}
```

**响应：**
```json
{
    "success": true,
    "message": "执行完成",
    "screenshot": "base64_encoded_image...",
    "current_app": "com.zhihu.android",
    "execution_time": 3.5
}
```

### POST /analyze
分析屏幕内容

**请求：**
```json
{
    "screenshot": "base64_encoded_image...",
    "question": "当前页面是否显示视频列表？",
    "context": "用户正在刷视频任务中"
}
```

**响应：**
```json
{
    "success": true,
    "answer": "是",
    "confidence": 0.95,
    "details": "检测到视频推荐列表，显示多个视频封面"
}
```

### POST /tasks
创建异步任务

**请求：**
```json
{
    "device_id": "192.168.1.100:5555",
    "task": "打开抖音刷10分钟视频",
    "use_knowledge": true,
    "max_steps": 50,
    "timeout": 600
}
```

**响应：**
```json
{
    "success": true,
    "task_id": "task_1234567890_1",
    "message": "任务已创建"
}
```

### GET /tasks/{task_id}
获取任务状态

**响应：**
```json
{
    "task_id": "task_1234567890_1",
    "status": "running",
    "progress": 15,
    "total_steps": 50,
    "current_action": "上滑切换视频",
    "message": "正在执行"
}
```

## Dify 工作流设计示例

### 示例 1：刷视频工作流

```yaml
name: 刷视频工作流
description: 自动刷短视频，支持时间控制和随机互动

nodes:
  - id: start
    type: start
    outputs:
      - task: string        # 任务描述
      - device_id: string   # 设备 ID
      - duration: number    # 时长（秒）

  - id: init_vars
    type: variable
    data:
      start_time: "{{#timestamp#}}"
      video_count: 0
      like_count: 0

  - id: launch_app
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "打开抖音"
        wait_after: 3

  - id: check_time
    type: condition
    data:
      conditions:
        - left: "{{#timestamp#}} - {{start_time}}"
          operator: "<"
          right: "{{duration}}"

  - id: swipe_video
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "上滑切换到下一个视频"
        wait_after: 5

  - id: random_like
    type: condition
    data:
      conditions:
        - left: "{{#random(0,10)#}}"
          operator: "<"
          right: "1"  # 10% 概率点赞

  - id: do_like
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "双击屏幕点赞"
        wait_after: 1

  - id: end
    type: end
    data:
      output:
        success: true
        video_count: "{{video_count}}"
        like_count: "{{like_count}}"
        message: "已浏览 {{video_count}} 个视频，点赞 {{like_count}} 次"

edges:
  - source: start
    target: init_vars
  - source: init_vars
    target: launch_app
  - source: launch_app
    target: check_time
  - source: check_time
    target: swipe_video
    condition: true
  - source: check_time
    target: end
    condition: false
  - source: swipe_video
    target: random_like
  - source: random_like
    target: do_like
    condition: true
  - source: random_like
    target: check_time
    condition: false
  - source: do_like
    target: check_time
```

### 示例 2：搜索购物工作流

```yaml
name: 搜索购物工作流
description: 在电商平台搜索商品

nodes:
  - id: start
    type: start
    outputs:
      - device_id: string
      - platform: string    # 淘宝/京东/拼多多
      - keyword: string     # 搜索关键词
      - max_price: number   # 最高价格

  - id: launch_app
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "打开{{platform}}"
        wait_after: 3

  - id: click_search
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "点击搜索框"
        wait_after: 1

  - id: input_keyword
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "输入 {{keyword}} 并搜索"
        wait_after: 3

  - id: get_screenshot
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/screenshot"
      body:
        device_id: "{{device_id}}"

  - id: analyze_results
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/analyze"
      body:
        screenshot: "{{get_screenshot.screenshot}}"
        question: "搜索结果中是否有价格低于 {{max_price}} 元的商品？如果有，请告诉我最便宜的商品名称和价格"

  - id: check_found
    type: condition
    data:
      conditions:
        - left: "{{analyze_results.answer}}"
          operator: "contains"
          right: "是"

  - id: click_product
    type: http_request
    data:
      method: POST
      url: "http://localhost:8765/execute"
      body:
        device_id: "{{device_id}}"
        instruction: "点击搜索结果中最便宜的商品"
        wait_after: 2

  - id: end_success
    type: end
    data:
      output:
        success: true
        message: "已找到符合条件的商品: {{analyze_results.details}}"

  - id: end_not_found
    type: end
    data:
      output:
        success: false
        message: "未找到价格低于 {{max_price}} 元的商品"

edges:
  - source: start
    target: launch_app
  - source: launch_app
    target: click_search
  - source: click_search
    target: input_keyword
  - source: input_keyword
    target: get_screenshot
  - source: get_screenshot
    target: analyze_results
  - source: analyze_results
    target: check_found
  - source: check_found
    target: click_product
    condition: true
  - source: check_found
    target: end_not_found
    condition: false
  - source: click_product
    target: end_success
```

## 混合模式使用建议

### 何时使用 Dify 工作流

1. **时间控制任务**：如"刷10分钟视频"、"浏览30分钟新闻"
2. **多步骤流程**：如"搜索商品→筛选→加购物车→下单"
3. **需要条件判断**：如"如果价格低于100就购买"
4. **需要计数/统计**：如"浏览10个商品"、"点赞5个视频"
5. **循环重复操作**：如"每隔5秒滑动一次"

### 何时使用纯 AI 模式

1. **简单单步操作**：如"打开微信"、"返回桌面"
2. **需要视觉理解**：如"找到红色的按钮点击"
3. **动态环境**：页面结构不固定，需要 AI 实时判断
4. **异常处理**：工作流遇到预期外情况时的 fallback

### 混合使用示例

```python
from core.dify_integration import TaskRouter, HybridExecutor

router = TaskRouter(dify_config)
executor = HybridExecutor(dify_config, phone_agent_executor, screenshot_getter)

# 自动路由
task = "在抖音刷10分钟视频，期间点赞3个喜欢的"
complexity, reason = router.analyze_task(task)
# 输出: COMPLEX - 需要时间控制或多步骤编排

# 执行（自动选择工作流或 AI）
success, message = executor.execute_task(task, device_id)
```

## 注意事项

1. **网络延迟**：云手机场景下 API 调用可能有延迟，建议设置合理的 `wait_after` 时间
2. **截图大小**：base64 截图数据较大，建议在必要时才获取
3. **错误处理**：工作流中应添加异常处理节点，避免单步失败导致整体中断
4. **状态同步**：长时间任务建议定期检查设备连接状态
5. **并发控制**：同一设备同时只能执行一个任务

## 故障排除

### API 服务器无法启动
- 检查端口 8765 是否被占用
- 确认已安装 fastapi 和 uvicorn：`pip install fastapi uvicorn`

### Dify 无法连接 API
- 检查防火墙设置
- 确认 API 服务器地址配置正确
- 测试 `/health` 接口是否可访问

### 执行超时
- 增加 `timeout` 参数值
- 检查设备网络连接
- 云手机场景建议 timeout >= 30 秒
