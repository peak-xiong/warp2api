# warp2api

Warp 多协议网关。  
单进程提供 OpenAI / Anthropic / Gemini 兼容接口，统一走 protobuf 上游链路与 token 池调度。

## 核心特性

- 单一上游发送链路（避免多实现分叉）
- 多协议兼容：
  - `POST /v1/chat/completions`（OpenAI）
  - `POST /v1/responses`（OpenAI）
  - `POST /v1/messages`（Anthropic）
  - `POST /v1/models/{model}:generateContent`（Gemini）
  - `POST /v1/models/{model}:streamGenerateContent`（Gemini Stream）
- Token 池后台能力：
  - SQLite 持久化
  - 定时保活刷新
  - 健康检查与可用性路由
  - 管理 API + 管理页面

## 快速开始

1. 安装依赖

```bash
uv sync
```

2. 配置环境变量（最小可用）

```env
# 服务鉴权（给你的客户端调用本服务时使用）
API_TOKEN=0000

# 管理端鉴权（访问 /admin/api/tokens/*）
ADMIN_TOKEN=change-me

# token 池数据库
WARP_TOKEN_DB_PATH=./data/token_pool.db

# 可选：token 加密 key（base64url 32 bytes）
WARP_TOKEN_ENCRYPTION_KEY=
```

3. 启动服务

```bash
uv run warp2api-gateway --port 28889
```

4. 健康检查

```bash
curl http://127.0.0.1:28889/healthz
```

## 常用接口

- `GET /healthz`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/messages`
- `POST /v1/models/{model}:generateContent`
- `POST /v1/models/{model}:streamGenerateContent`
- `GET /admin/tokens`（管理 UI）
- `GET /admin/api/tokens`
- `POST /admin/api/tokens/batch-import`
- `POST /admin/api/tokens/{id}/refresh`
- `GET /admin/api/tokens/statistics`
- `GET /admin/api/tokens/health`
- `GET /admin/api/tokens/readiness`

## 部署（PM2）

```bash
pm2 start ecosystem.config.cjs
pm2 status
pm2 logs warp2api-gateway
```

## 目录结构

```text
warp2api/
├── src/warp2api/
│   ├── adapters/            # OpenAI / Anthropic / Gemini 适配层
│   ├── api/                 # HTTP 路由与请求模型
│   ├── app/                 # 进程入口与启动编排
│   ├── application/         # 用例服务（网关、token 池、调度）
│   ├── domain/              # 领域模型
│   ├── infrastructure/      # protobuf、传输、鉴权、存储
│   ├── observability/       # 日志
│   ├── proto/               # proto 定义
│   └── tools/               # proto 同步工具
├── static/                  # 管理页面静态资源
├── tests/                   # 测试
├── docs/                    # 架构与设计文档
├── ecosystem.config.cjs     # PM2 配置
└── pyproject.toml           # Python 项目配置
```

## 开发与测试

```bash
uv run pytest -q
```

## 说明

- 该项目已移除旧入口与历史脚本，统一使用 `uv` + `pyproject` 脚本。
- 不存在 token 时不会兜底，接口会直接返回不可用状态，便于你及时感知资源问题。
