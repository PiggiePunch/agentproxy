# OpenClaw 对话追踪上报 API 文档

## 接口地址

```
POST http://{服务器地址}:8000/traces
```

## 请求格式

- Content-Type: `application/json`
- Body 为一个 JSON 对象，包含一次完整对话的追踪数据

## 必填字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `steps` | Array | **是** | 对话步骤列表，至少包含1个元素 |

其他顶层字段可选，但建议尽量提供以便前端展示更完整。

## 完整 JSON 结构

```json
{
  "trace_id": "8cf7a3cc-646d-4613-ad95-7db6fb0b786d",
  "agent_id": "agent:main:dashboard:c7b0d780-eb3f-4e4f-8865-63b368b79556",
  "started_at": "2026-05-20T10:02:45.971",
  "duration_seconds": 21.6,
  "steps": [
    {
      "step_index": 1,
      "type": "run",
      "name": "main",
      "run_id": "9da71568",
      "offset_seconds": 0,
      "duration_seconds": 20.5,
      "depth": 0,
      "detail": {
        "tokens_in": 17000,
        "tokens_out": 778,
        "tokens_cache": 47100,
        "query": "帮我查查上海的日本料理",
        "reply_summary": "推荐内容摘要..."
      }
    },
    {
      "step_index": 2,
      "type": "model",
      "name": "custom-api-siliconflow-glm-4-7",
      "offset_seconds": 1.1,
      "duration_seconds": 5.9,
      "depth": 1,
      "detail": {
        "ttft_seconds": 3.9,
        "bytes_request": 57900,
        "bytes_response": 133200,
        "in_context_query_chars": 150
      }
    },
    {
      "step_index": 3,
      "type": "tool",
      "name": "read",
      "offset_seconds": 7.2,
      "duration_seconds": 0.229,
      "depth": 1,
      "detail": {
        "skill": "/shanghai-foodie",
        "file": "~/.openclaw/workspace/skills/shanghai-foodie/SKILL.md",
        "result_summary": "读取技能文件内容..."
      }
    }
  ],
  "summary": {
    "model_calls": 4,
    "tool_calls": 3,
    "tokens_in": 17000,
    "tokens_out": 778,
    "tokens_cache": 47100,
    "model_time_seconds": 19.4,
    "top_tools": {"exec": 2, "read": 1}
  }
}
```

## 字段详细说明

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | String | 本次对话的唯一标识（由插件生成） |
| `agent_id` | String | 代理实例标识 |
| `started_at` | String | 对话开始时间，ISO 8601 格式（如 `2026-05-20T10:02:45.971`） |
| `duration_seconds` | Number | 整次对话的总耗时（秒） |
| `steps` | Array | 步骤列表，按执行顺序排列 |
| `summary` | Object | 对话统计摘要 |

### 步骤字段（steps 数组中每个对象）

| 字段 | 类型 | 说明 |
|------|------|------|
| `step_index` | Integer | 步骤序号，从1开始 |
| `type` | String | 步骤类型，三种取值：`run`(主流程)、`model`(模型调用)、`tool`(工具调用) |
| `name` | String | 步骤名称，如模型名、工具名 |
| `offset_seconds` | Number | 该步骤相对于对话开始的偏移时间（秒） |
| `duration_seconds` | Number | 该步骤自身的耗时（秒） |
| `depth` | Integer | 层级深度，0=主流程，1=子步骤 |
| `detail` | Object | 步骤详情，按 type 不同包含不同字段（见下） |

### detail 字段 — 按 type 分类

#### type=run（主流程）

| 字段 | 类型 | 说明 |
|------|------|------|
| `tokens_in` | Integer | 输入 token 数 |
| `tokens_out` | Integer | 输出 token 数 |
| `tokens_cache` | Integer | 缓存 token 数 |
| `query` | String | 用户原始提问 |
| `reply_summary` | String | 模型回复摘要 |

#### type=model（模型调用）

| 字段 | 类型 | 说明 |
|------|------|------|
| `ttft_seconds` | Number | 首 token 时延（秒） |
| `bytes_request` | Integer | 请求字节数 |
| `bytes_response` | Integer | 响应字节数 |
| `in_context_query_chars` | Integer | 上下文中查询的字符数 |

#### type=tool（工具调用）

| 字段 | 类型 | 说明 |
|------|------|------|
| `command` | String | 执行的命令（exec 类型工具） |
| `file` | String | 读取的文件路径（read 类型工具） |
| `skill` | String | 技能名称（skill 类型工具） |
| `result_summary` | String | 工具执行结果摘要 |

> detail 中的字段不是固定的，按实际情况填写即可，未用到的字段可以省略。

### summary 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `model_calls` | Integer | 模型调用总次数 |
| `tool_calls` | Integer | 工具调用总次数 |
| `tokens_in` | Integer | 输入 token 总数 |
| `tokens_out` | Integer | 输出 token 总数 |
| `tokens_cache` | Integer | 缓存 token 总数 |
| `model_time_seconds` | Number | 模型总耗时（秒） |
| `top_tools` | Object | 工具调用次数统计，key=工具名，value=调用次数 |

## 响应

### 成功（201）

```json
{
  "status": "ok",
  "storage_id": "服务器生成的存储ID"
}
```

### 失败（400）

```json
{
  "error": "'steps' must be a non-empty array"
}
```

## 调用示例（Python）

```python
import requests

trace_data = {
    "trace_id": "唯一ID",
    "started_at": "2026-05-27T10:00:00.000",
    "duration_seconds": 15.2,
    "steps": [
        {"step_index": 1, "type": "run", ...},
        {"step_index": 2, "type": "model", ...},
    ],
    "summary": {"model_calls": 1, "tool_calls": 0, ...}
}

resp = requests.post("http://localhost:8000/traces", json=trace_data)
print(resp.status_code, resp.json())
# 201 {"status": "ok", "storage_id": "..."}
```

## 注意事项

1. 每次对话结束后上报一次即可，一次上报包含整次对话的所有步骤
2. `steps` 是唯一必填字段，其余字段可选但建议填写以获得更好的展示效果
3. 服务器最多保留 200 条追踪记录，超出后自动淘汰最老的记录
4. `offset_seconds` 和 `duration_seconds` 用来绘制甘特图时间轴，请尽量准确