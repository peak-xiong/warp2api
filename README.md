# warp2api

基于 Python 的桥接服务，为 Warp AI 服务提供 OpenAI Chat Completions API 兼容性，通过利用 Warp 的 protobuf 基础架构，实现与 OpenAI 兼容应用程序的无缝集成。

## 🚀 特性

- **OpenAI API 兼容性**: 完全支持 OpenAI Chat Completions API 格式
- **Warp 集成**: 使用 protobuf 通信与 Warp AI 服务无缝桥接
- **统一网关架构**:
  - 单服务同时提供 OpenAI/Anthropic/Gemini 兼容接口
  - 内置 protobuf 编解码与 Warp 诊断接口
- **JWT 认证**: Warp 服务的自动令牌管理和刷新
- **流式支持**: 与 OpenAI SSE 格式兼容的实时流式响应
- **WebSocket 监控**: 内置监控和调试功能
- **消息重排序**: 针对 Anthropic 风格对话的智能消息处理

## 📋 系统要求

- Python 3.9+ (推荐 3.13+)
- Warp AI 服务访问权限（JWT 令牌会自动获取）
- 支持 Linux、macOS 和 Windows

## 🛠️ 安装

1. **克隆仓库:**
   ```bash
   git clone <repository-url>
   cd warp2api
   ```

2. **使用 uv 安装依赖 (推荐):**
   ```bash
   uv sync
   ```

   或使用 pip:
   ```bash
   pip install -e .
   ```

3. **配置环境变量:**
    程序会自动获取匿名JWT TOKEN，您无需手动配置。

    如需自定义配置，可以创建 `.env` 文件:
    ```env
    # warp2api 配置
    # 设置为 true 启用详细日志输出，默认 false（静默模式）
    W2A_VERBOSE=false

    # 禁用代理以避免连接问题
    HTTP_PROXY=
    HTTPS_PROXY=
    NO_PROXY=127.0.0.1,localhost

    # 管理端鉴权（/admin/api/tokens/*）
    ADMIN_TOKEN=change-me

    # 可选：使用自己的Warp凭证（不推荐，会消耗订阅额度）
    WARP_JWT=your_jwt_token_here
    WARP_REFRESH_TOKEN=your_refresh_token_here

    # Token 池存储与加密（可选）
    WARP_TOKEN_DB_PATH=./data/token_pool.db
    WARP_TOKEN_ENCRYPTION_KEY=base64url-32bytes-key
    ```

## 🎯 使用方法

### 快速开始

#### 方法一：一键启动脚本（推荐）

**Linux/macOS:**
```bash
# 启动所有服务器
./start.sh

# 停止所有服务器
./stop.sh

# 查看服务器状态
./stop.sh status
```

**Windows:**
```batch
REM 使用批处理脚本
start.bat          # 启动服务器
stop.bat           # 停止服务器
stop.bat status    # 查看服务器状态
test.bat           # 测试API接口功能

REM 或使用 PowerShell 脚本
.\start.ps1        # 启动服务器
.\start.ps1 -Stop  # 停止服务器
.\start.ps1 -Verbose  # 启用详细日志

REM 测试脚本
test.bat           # 测试API接口功能（静默模式）
test.bat -v        # 测试API接口功能（详细模式）
```

启动脚本会自动：
- ✅ 检查Python环境和依赖
- ✅ 自动配置环境变量（包括API_TOKEN自动设置为"0000"）
- ✅ 启动统一 API 服务器
- ✅ 验证服务器健康状态（循环检查healthz端点）
- ✅ 显示关键配置信息
- ✅ 显示完整的 API 接口 Token
- ✅ 显示 Roocode / KiloCode baseUrl
- ✅ 实时监控服务器日志（verbose模式）
- ✅ 提供详细的错误处理和状态反馈

### 📸 运行演示

#### 项目启动界面
![项目启动界面](docs/screenshots/运行截图.png)

#### 使用示例
![使用示例](docs/screenshots/使用截图.png)

#### 方法二：手动启动

1. **启动多协议网关服务器:**
   ```bash
   uv run warp2api-gateway --port 28889
   ```
   默认地址: `http://localhost:28889`

### 支持的模型

warp2api 支持以下 AI 模型：

#### 核心模型
- `auto`
- `claude-4-sonnet`
- `claude-4.1-opus`
- `claude-4.5-haiku`
- `claude-4.5-sonnet`
- `claude-4.5-opus`
- `claude-4.6-sonnet`
- `claude-4.6-opus`
- `gemini-2.5-pro`
- `gemini-3-pro`
- `glm-4.7-us-hosted`
- `gpt-5`
- `gpt-5.1`
- `gpt-5.2`
- `gpt-5.3-codex`

完整列表请以 `GET /v1/models` 返回为准。

### 使用 API

#### 🔓 认证说明
**重要：warp2api 的 OpenAI 兼容接口不需要 API key 验证！**

- 服务器会自动处理 Warp 服务的认证
- 客户端可以发送任意的 `api_key` 值（或完全省略）
- 所有请求都会使用系统自动获取的匿名 JWT token

服务启动后，您可以使用任何 OpenAI 兼容的客户端:

#### Python 示例
```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:28889/v1",
    api_key="dummy"  # 可选：某些客户端需要，但服务器不强制验证
)

response = client.chat.completions.create(
    model="claude-4-sonnet",  # 选择支持的模型
    messages=[
        {"role": "user", "content": "你好，你好吗？"}
    ],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

#### cURL 示例
```bash
# 基本请求
curl -X POST http://localhost:28889/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-4-sonnet",
    "messages": [
      {"role": "user", "content": "你好，请介绍一下你自己"}
    ],
    "stream": true
  }'

# 指定其他模型
curl -X POST http://localhost:28889/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5",
    "messages": [
      {"role": "user", "content": "解释量子计算的基本原理"}
    ],
    "temperature": 0.7,
    "max_tokens": 1000
  }'
```

#### JavaScript/Node.js 示例
```javascript
const OpenAI = require('openai');

const client = new OpenAI({
  baseURL: 'http://localhost:28889/v1',
  apiKey: 'dummy'  // 可选：某些客户端需要，但服务器不强制验证
});

async function main() {
  const completion = await client.chat.completions.create({
    model: 'gemini-2.5-pro',
    messages: [
      { role: 'user', content: '写一个简单的Hello World程序' }
    ],
    stream: true
  });

  for await (const chunk of completion) {
    process.stdout.write(chunk.choices[0]?.delta?.content || '');
  }
}

main();
```

### 模型选择建议

- **编程任务**: 推荐使用 `claude-4-sonnet` 或 `gpt-5`
- **创意写作**: 推荐使用 `claude-4.6-opus` 或 `gpt-5.2`
- **代码审查**: 推荐使用 `claude-4.1-opus`
- **推理任务**: 推荐使用 `gpt-5.3-codex` 或 `claude-4.6-opus-max`
- **轻量任务**: 推荐使用 `claude-4.5-haiku` 或 `gpt-5.1`

### 可用端点

#### Unified API 服务器 (`http://localhost:28889`)
- `GET /` - 服务状态
- `GET /healthz` - 健康检查
- `GET /v1/models` - 模型列表
- `POST /v1/chat/completions` - OpenAI Chat Completions 兼容端点
- `POST /v1/responses` - OpenAI Responses 兼容端点
- `POST /v1/messages` - Anthropic Messages 兼容端点
- `POST /v1/models/{model}:generateContent` - Gemini 兼容端点
- `POST /v1/models/{model}:streamGenerateContent` - Gemini 流式端点
- `POST /api/encode` - JSON 编码为 protobuf（诊断）
- `POST /api/decode` - protobuf 解码为 JSON（诊断）
- `POST /api/warp/send_stream` - Warp 请求诊断与事件查看
- `GET /api/warp/token_pool/status` - token 池状态
- `GET /admin/tokens` - 管理 UI 页面
- `GET /admin/api/tokens` - 管理端 token 列表（需 `ADMIN_TOKEN`）
- `POST /admin/api/tokens/batch-import` - 批量导入 refresh token
- `PATCH /admin/api/tokens/{id}` - 修改 label/status
- `POST /admin/api/tokens/{id}/refresh` - 手动 refresh
- `GET /admin/api/tokens/statistics` - 管理统计
- `GET /admin/api/tokens/health` - 后台健康检查快照
- `GET /admin/api/tokens/readiness` - 是否可接流量（可用 token / 恢复时间）
- `GET /admin/api/tokens/events` - 审计事件

说明：运行时只使用 SQLite token 池。若 token 池为空或无可用 token，请求会直接返回 503，不再使用环境变量兜底。
调度策略：仅从可用账号中分发（排除 `blocked/quota_exhausted/disabled/冷却中/连续健康失败`），并使用健康约束轮询以实现更均匀负载。

## 🏗️ 架构

```
┌─────────────────┐    ┌──────────────────────────────────────────┐    ┌─────────────────┐
│    客户端应用     │───▶│ warp2api Unified API (端口 28889)        │───▶│    Warp AI      │
│  (OpenAI SDK)   │    │ OpenAI/Anthropic/Gemini + 诊断接口        │    │      服务       │
└─────────────────┘    └──────────────────────────────────────────┘    └─────────────────┘
```

### 核心组件

- **`src/warp2api/adapters/`**: 协议适配层（OpenAI/Anthropic/Gemini）
  - 仅处理 HTTP 路由与协议格式转换
  - 不承载核心业务编排逻辑

- **`src/warp2api/application/services/`**: 应用编排层（主逻辑）
  - 请求鉴权、Bridge 预热、会话状态管理
  - Warp packet 构造与响应事件聚合
  - OpenAI/Responses 协议数据转换

- **`src/warp2api/infrastructure/`**: 底层能力层
  - Protobuf 编解码与运行时
  - Warp 传输与事件解析
  - 认证刷新、账号池监控、配置管理

## 🔧 配置

### 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `WARP_JWT` | Warp 认证 JWT 令牌 | 自动获取 |
| `WARP_REFRESH_TOKEN` | JWT 刷新令牌 | 可选 |
| `HTTP_PROXY` | HTTP 代理设置 | 空（禁用代理） |
| `HTTPS_PROXY` | HTTPS 代理设置 | 空（禁用代理） |
| `NO_PROXY` | 不使用代理的主机 | `127.0.0.1,localhost` |
| `HOST` | 服务器主机地址 | `127.0.0.1` |
| `PORT` | 多协议网关服务器端口 | `28889` |
| `API_TOKEN` | API接口认证令牌 | `0000`（自动设置） |
| `ADMIN_TOKEN` | 管理接口鉴权令牌 | 空（未设置则管理接口不可用） |
| `WARP_ADMIN_AUTH_MODE` | 管理接口鉴权模式（`token`/`local`/`off`） | `token` |
| `WARP_TOKEN_DB_PATH` | token 池 SQLite 路径 | `./data/token_pool.db` |
| `WARP_TOKEN_ENCRYPTION_KEY` | token 加密密钥(base64url 32字节) | 自动派生（仅开发建议） |
| `WARP_POOL_REFRESH_INTERVAL_SECONDS` | token 后台保活刷新周期 | `3600` |
| `W2A_VERBOSE` | 启用详细日志输出 | `false` |

### 项目脚本

在 `pyproject.toml` 中定义:

```bash
# 启动多协议网关服务器
warp-gateway

# 统一启动器
warp2api --mode openai

# proto 校验
warp2api-proto check

# 与外部 proto 目录做差异对比
warp2api-proto diff --against /path/to/proto --show-patch

# 从 Warp 二进制提取 proto（可选直接覆盖到项目）
warp2api-proto extract --output /tmp/warp-proto
warp2api-proto extract --output /tmp/warp-proto --apply
```

## 🔐 认证

服务会自动处理 Warp 认证:

1. **JWT 管理**: 自动令牌验证和刷新
2. **匿名访问**: 在需要时回退到匿名令牌
3. **令牌持久化**: 安全的令牌存储和重用

## 🧪 开发

### 项目结构

``` 
warp2api/
├── src/warp2api/
│   ├── domain/              # 领域模型与策略
│   ├── application/         # 应用服务编排（主逻辑）
│   ├── infrastructure/      # protobuf/传输/认证/监控实现
│   ├── adapters/            # OpenAI/Anthropic/Gemini 协议适配
│   └── app/                 # 服务入口与启动
│   └── proto/               # Warp proto 定义
├── server.py                # Unified API 服务器
├── openai_compat.py         # 多协议网关服务器入口
├── start.sh                 # Linux/macOS 启动脚本
├── stop.sh                  # Linux/macOS 停止脚本
├── test.sh                  # Linux/macOS 测试脚本
├── start.bat                # Windows 批处理启动脚本
├── stop.bat                 # Windows 批处理停止脚本
├── test.bat                 # Windows 批处理测试脚本
├── start.ps1                # Windows PowerShell 启动脚本
├── docs/                    # 项目文档
│   ├── TROUBLESHOOTING.md   # 故障排除指南
│   ├── current_architecture.md # 当前架构说明（最新）
│   └── screenshots/         # 项目截图
└── pyproject.toml           # 项目配置
```

### 截图演示

项目运行截图和界面演示请查看 [`docs/screenshots/`](docs/screenshots/) 文件夹。

## 📋 文档

主要依赖项包括:
- **FastAPI**: 现代、快速的 Web 框架
- **Uvicorn**: ASGI 服务器实现
- **HTTPx**: 支持 HTTP/2 的异步 HTTP 客户端
- **Protobuf**: Protocol buffer 支持
- **WebSockets**: WebSocket 通信
- **OpenAI**: 用于类型兼容性

存储架构文档：
- [`docs/data_storage_architecture.md`](docs/data_storage_architecture.md)

管理鉴权说明：
- `WARP_ADMIN_AUTH_MODE=token`：默认，必须传 `ADMIN_TOKEN`
- `WARP_ADMIN_AUTH_MODE=local`：仅本机请求可免 token（个人使用推荐）
- `WARP_ADMIN_AUTH_MODE=off`：完全关闭管理鉴权（仅限内网/开发）

## 🐛 故障排除

详细的故障排除指南请参考 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

### 常见问题

1. **"Server disconnected without sending a response" 错误**
    - 确保代理设置已禁用：`HTTP_PROXY=`, `HTTPS_PROXY=`, `NO_PROXY=127.0.0.1,localhost`
    - 检查防火墙是否阻止了本地连接

2. **JWT 令牌过期**
    - 服务会自动刷新令牌
    - 检查日志中的认证错误
    - 验证 `WARP_REFRESH_TOKEN` 是否有效

3. **代理连接错误**
    - 如果遇到 `ProxyError` 或端口 1082 错误
    - 在 `.env` 文件中设置：`HTTP_PROXY=`, `HTTPS_PROXY=`, `NO_PROXY=127.0.0.1,localhost`
    - 或者在系统环境中禁用代理

4. **连接错误**
    - 检查到 Warp 服务的网络连接
    - 验证防火墙设置
    - 确保本地端口 28889 未被其他应用占用

### 日志记录

服务提供详细的日志记录:
- 认证状态和令牌刷新
- 请求/响应处理
- 错误详情和堆栈跟踪
- 性能指标

## 📄 许可证

该项目配置为内部使用。请与项目维护者联系了解许可条款。

## 🤝 贡献

1. Fork 仓库
2. 创建功能分支
3. 进行更改
4. 如适用，添加测试
5. 提交 pull request

## 📞 支持

如有问题和疑问:
1. 查看故障排除部分
2. 查看服务器日志获取错误详情
3. 创建包含重现步骤的 issue
