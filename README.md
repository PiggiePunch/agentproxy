# AgentProxy

一个轻量级的 OpenAI / Anthropic API 代理服务，帮你把 AI 调用转发到真实大模型接口，同时本地记录完整请求/响应、性能指标和会话信息，并通过可视化控制台实时查看。

> 核心定位：**不修改上层应用代码，只需改一行 Base URL，即可拥有本地日志、性能监控和会话追踪能力。**

## 功能特性

- **双协议代理**：同时支持 OpenAI (`/v1/chat/completions`) 和 Anthropic (`/v1/messages`) 格式
- **流式 & 非流式**：SSE 流式和普通 JSON 请求都透明转发
- **完整落盘日志**：请求体、响应体、性能指标按请求 ID 本地保存
- **性能监控**：总耗时、代理耗时、模型耗时、首 Token 时延、输入/输出 Token、请求间隔
- **会话追踪**：支持 `X-Session-Id` 请求头，未携带时自动按消息链推断会话
- **可视化控制台**：KPI 卡片、趋势折线图、请求表格、会话过滤、深浅主题切换
- **对话追踪**：展开单次对话的模型调用、工具调用和耗时瀑布
- **工具调用检测**：自动识别请求中是否包含工具调用
- **自动日志清理**：默认保留 3 天日志，避免磁盘无限增长

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置真实 API 地址

```bash
cp .env.example .env
```

编辑 `.env`，根据你要代理的格式配置上游地址：

```env
# OpenAI 格式（chat.completions 等）
REAL_API_URL=https://api.moonshot.cn/v1

# Anthropic 格式（messages 等）
# ANTHROPIC_API_URL=https://api.anthropic.com
```

- 如果只代理 OpenAI 格式，配 `REAL_API_URL` 即可
- 如果只代理 Anthropic 格式，把 `ANTHROPIC_API_URL` 取消注释并配置
- 两种都代理就两个都配

### 3. 启动服务

```bash
python backend/main.py
```

控制台默认运行在 http://localhost:8000/dashboard

## 客户端配置

代理通过请求路径区分格式，把请求转发到对应上游：

| 格式 | 代理端点 | 转发到 |
|---|---|---|
| OpenAI | `POST /v1/chat/completions` | `REAL_API_URL` |
| Anthropic | `POST /v1/messages` | `ANTHROPIC_API_URL` |

### 自己写 HTTP 请求

如果你不用 SDK，直接按真实 API 的格式发请求，只是把地址改成代理地址：

```bash
# OpenAI 格式
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer 你的真实Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "hello"}]
  }'

# Anthropic 格式
curl http://localhost:8000/v1/messages \
  -H "x-api-key: 你的真实Key" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

### 使用 SDK

如果用 SDK，把 Base URL 改成代理地址即可，API Key 仍然填真实 Key：

| SDK | Base URL | 说明 |
|---|---|---|
| OpenAI SDK | `http://localhost:8000/v1` | SDK 会自动拼接 `/chat/completions` |
| Anthropic SDK | `http://localhost:8000` | SDK 会自动拼接 `/v1/messages` |

#### OpenAI SDK 示例

```python
from openai import OpenAI

client = OpenAI(
    api_key="你的真实 API Key",
    base_url="http://localhost:8000/v1"
)

client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "hello"}]
)
```

#### Anthropic SDK 示例

```python
import anthropic

client = anthropic.Anthropic(
    api_key="你的真实 API Key",
    base_url="http://localhost:8000"
)

client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "hello"}]
)
```

## 常用配置

在 `.env` 中配置：

```env
# OpenAI 格式上游（chat.completions 等）
REAL_API_URL=https://api.openai.com/v1

# Anthropic 格式上游（messages 等）
ANTHROPIC_API_URL=https://api.anthropic.com

# 服务监听地址和端口
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# 会话识别请求头
SESSION_HEADER=X-Session-Id

# 详细日志开关
VERBOSE_LOGGING=true

# 日志保留天数
LOG_RETENTION_DAYS=3
```

- `REAL_API_URL`：OpenAI 格式请求会转发到这里
- `ANTHROPIC_API_URL`：Anthropic 格式请求会转发到这里

如果只用其中一种格式，另一种可以不配；代码里有各自的默认地址。

## 访问入口

启动后打开：

- **控制台**：http://localhost:8000/dashboard
- **健康检查**：http://localhost:8000/
- **OpenAI 端点**：`POST /v1/chat/completions`
- **Anthropic 端点**：`POST /v1/messages`

## 控制台预览

控制台提供浅色/深色双主题，支持：

- 顶部 KPI 卡片实时展示请求量、平均耗时、成功率等
- 响应时间趋势折线图
- 最近请求记录表格，支持按会话过滤
- 点击表格行可查看完整请求/响应日志
- 追踪页查看单次对话的模型/工具调用瀑布

## 注意事项

1. **代理不保存你的 API Key**：客户端发送的 `Authorization` 头会原样转发给真实 API
2. **日志中可能包含敏感信息**：生产环境请注意日志文件权限和留存策略
3. **首次启动会自动创建 `logs/` 目录**：包括 `requests`、`responses`、`metrics`、`traces` 四个子目录
4. **纯 Python 标准库后端**：后端核心无第三方依赖，`requirements.txt` 为可选增强

## 目录说明

```
agentproxy/
├── backend/          # 代理服务与 API
├── frontend/        # 可视化控制台
├── logs/            # 本地日志和指标（自动生成）
├── .env.example     # 环境变量示例
└── backend/main.py  # 启动入口
```

## License

与原项目保持一致。
