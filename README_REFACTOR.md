# OpenClaw Proxy Server - 重构版本

## 项目重构说明

本项目已按照标准的Python项目结构进行了重构，实现了清晰的代码分层和模块化设计。

## 新的项目结构

```
agentproxy/
├── backend/                    # 后端服务
│   ├── __init__.py            # 包初始化
│   ├── main.py                # 主入口文件
│   ├── config.py              # 配置管理
│   ├── handlers/              # HTTP请求处理层
│   │   ├── __init__.py
│   │   ├── base.py            # 基础处理器
│   │   └── api_handler.py     # API接口处理
│   ├── services/              # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── log_service.py     # 日志服务
│   │   ├── metrics_service.py # 性能指标服务
│   │   ├── proxy_service.py   # 代理核心服务
│   │   └── stream_handler.py  # 流式请求处理
│   ├── utils/                 # 工具函数层
│   │   ├── __init__.py
│   │   ├── logger.py          # 日志工具
│   │   ├── helpers.py         # 辅助函数
│   │   └── converters.py      # 格式转换
│   └── models/                # 数据模型层
│       ├── __init__.py
│       └── request.py         # 请求数据模型
├── frontend/                   # 前端界面
│   ├── index.html             # 主页面
│   ├── static/                # 静态资源
│   │   ├── css/
│   │   │   └── style.css      # 样式文件
│   │   └── js/
│   │       └── app.js         # 前端逻辑
│   └── assets/                # 第三方库
│       └── js/
│           └── chart.umd.min.js
├── logs/                       # 日志目录
│   ├── requests/              # 请求日志
│   ├── responses/             # 响应日志
│   └── metrics/               # 性能指标
├── tests/                      # 测试目录
├── proxy_server.py            # 原始单文件版本（保留作为参考）
├── dashboard.html             # 原始单文件界面（保留作为参考）
├── requirements.txt           # Python依赖
└── .env.example               # 环境变量示例
```

## 重构改进

### 1. 代码分层
- **配置层** (`config.py`): 集中管理所有配置参数
- **数据模型层** (`models/`): 定义请求、响应、指标的数据结构
- **工具函数层** (`utils/`): 提供通用工具函数和格式转换
- **业务逻辑层** (`services/`): 核心业务逻辑实现
- **请求处理层** (`handlers/`): HTTP请求处理和路由分发

### 2. 前后端分离
- **前端**: 独立的HTML、CSS、JavaScript文件
- **后端**: 模块化的Python代码结构
- **API接口**: 清晰的RESTful API设计

### 3. 可维护性提升
- **模块化**: 每个模块职责单一，便于维护
- **可测试性**: 分层架构便于单元测试
- **可扩展性**: 新功能可以独立开发，不影响现有代码

### 4. 无外部依赖
- **纯Python标准库**: 后端仍然只使用Python标准库
- **原生JavaScript**: 前端使用原生JavaScript，无框架依赖
- **本地Chart.js**: 使用本地Chart.js文件，无需网络

## 启动方式

### 使用重构后的版本
```bash
cd /mnt/d/git/agentproxy
python backend/main.py
```

### 使用原始版本
```bash
cd /mnt/d/git/agentproxy
python proxy_server.py
```

## 访问地址

- **控制台**: http://localhost:8000/dashboard
- **API端点**: http://localhost:8000/
- **健康检查**: http://localhost:8000/

## 环境变量

可以通过环境变量自定义配置：

```bash
export REAL_API_URL="https://api.deepseek.com"
export ANTHROPIC_API_URL="https://open.bigmodel.cn/api/anthropic"
export SERVER_HOST="0.0.0.0"
export SERVER_PORT="8000"
export LOG_RETENTION_DAYS="3"
export VERBOSE_LOGGING="true"
```

## 功能特性

- ✅ 支持 OpenAI 和 Anthropic 两种 API 格式
- ✅ 请求/响应拦截和日志记录
- ✅ 流式和非流式传输支持
- ✅ 性能监控和指标分析
- ✅ 实时数据可视化
- ✅ 自动日志清理
- ✅ 工具调用检测
- ✅ Token 使用统计

## 技术栈

### 后端
- Python 3.8+
- http.server (标准库)
- threading (标准库)
- json, pathlib, datetime (标准库)

### 前端
- HTML5
- CSS3 (CSS Variables, Flexbox, Grid)
- 原生 JavaScript (ES6+)
- Chart.js (本地版本)

## 开发说明

### 添加新的API端点
1. 在 `backend/handlers/api_handler.py` 中添加处理方法
2. 在相应的 `do_GET`, `do_POST`, `do_DELETE` 方法中添加路由

### 修改前端样式
1. 编辑 `frontend/static/css/style.css`
2. 修改 CSS 变量或样式规则

### 添加前端功能
1. 编辑 `frontend/static/js/app.js`
2. 添加新的 JavaScript 函数和事件处理

### 修改配置
1. 编辑 `backend/config.py`
2. 添加新的配置参数和默认值

## 注意事项

1. **无破坏性重构**: 原始文件 (`proxy_server.py`, `dashboard.html`) 被保留，可以继续使用
2. **功能一致性**: 重构版本功能与原始版本完全一致
3. **兼容性**: 保持了所有原有的API端点和功能
4. **性能**: 重构后的代码性能与原始版本相当

## 未来改进方向

- [ ] 添加单元测试覆盖
- [ ] 支持配置文件（YAML/JSON）
- [ ] 添加更多API指标监控
- [ ] 支持多实例部署
- [ ] 添加用户认证功能
- [ ] 支持更多AI模型格式

## 许可证

与原项目保持一致

## 贡献

欢迎提交 Issue 和 Pull Request！