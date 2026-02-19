# warp2api `src` 结构迁移规划（归档）

> 说明：本文档保留迁移过程记录与阶段性分析，包含历史路径描述。
> 当前可执行架构请优先参考 `docs/current_architecture.md` 与 `docs/clean_architecture_scaffold.md`。

## 1. 目标
在不改变现有 API 行为的前提下，将当前项目重构为更清晰、可维护、可测试的标准 Python 服务结构（`src` 布局）。

核心目标：
- 保持外部接口兼容（现有 OpenAI 兼容接口、Warp 相关接口不变）
- 降低模块耦合，明确分层边界
- 让“协议适配 / 业务编排 / 基础设施”职责分离
- 为后续扩展（模型策略、鉴权策略、可观测性）预留结构


## 2. 现状问题（摘要）
- 双入口目录并行（`warp2protobuf`、`protobuf2openai`），边界不够清晰。
- 路由层与执行策略层仍有交叉，命名上对“适配层 vs 核心层”不够直观。
- 部分模块以历史兼容为主，缺少统一的包边界与导入路径规范。
- 测试刚起步，缺少更系统的分层测试目录。

## 2.1 架构缺陷审计（当前代码，按优先级）

### P0（必须优先处理）
1. 全局会话状态污染（并发安全问题）
- 现状：`protobuf2openai/state.py` 使用全局 `STATE` 保存 `conversation_id / task_id`。
- 风险：多用户并发时会串会话，导致上下文错乱、响应串线、难以复现的 4xx/语义错误。
- 方案：改为“每请求会话上下文”或“显式 session_id -> state 存储（TTL）”，禁止全局共享会话变量。

2. 异步路由中使用同步 I/O（吞吐与延迟问题）
- 现状：`protobuf2openai/router.py`、`protobuf2openai/bridge.py` 在 async 路由链路中大量使用 `requests`。
- 风险：阻塞事件循环，导致高并发下吞吐下降、超时放大。
- 方案：统一改为 `httpx.AsyncClient`，封装到 infrastructure transport/client 层。

3. 默认内置敏感 fallback（安全与可控性问题）
- 现状：`warp2protobuf/config/settings.py` 含硬编码 `REFRESH_TOKEN_B64` 默认值。
- 风险：配置来源不透明，生产环境行为不可控，存在安全审计风险。
- 方案：生产模式禁用硬编码 fallback，仅允许环境变量显式提供；缺失时启动失败。

### P1（应在迁移中期完成）
4. 适配层与基础设施耦合偏高
- 现状：`protobuf2openai/*` 直接感知 bridge URL、请求重试细节。
- 风险：协议适配改动会牵动传输层，维护成本高。
- 方案：引入 `application/services` + `infrastructure/providers/warp_provider.py`，adapter 仅做协议映射。

5. 重复逻辑仍然存在
- 现状：`encode_smd_inplace` 与 `_encode_smd_inplace` 在不同模块重复实现思路。
- 风险：行为漂移、修复遗漏。
- 方案：收敛为单一实现（infrastructure/protobuf/codec.py），其余模块只调用。

6. 鉴权与配置初始化有模块副作用
- 现状：`protobuf2openai/auth.py` 导入时 `load_dotenv(override=True)` + 初始化全局 auth 实例。
- 风险：测试与运行环境行为不可预测。
- 方案：改为 app startup 时显式加载配置与构建依赖，避免 import side effects。

### P2（优化项）
7. 文档与实现分层术语尚未完全一致
- 现状：部分文件命名仍偏历史语义（`warp2protobuf`/`protobuf2openai`）。
- 方案：Phase 5 收敛命名与兼容层下线。

8. 测试层级不足
- 现状：已有 smoke，但缺少 OpenAI/Anthropic/Gemini adapter 的契约测试与并发测试。
- 方案：补充 contract test + 并发隔离测试（重点验证会话不串线）。

## 2.2 问题清单（Issue -> Action -> DoD）

| Priority | Issue | 影响 | 改造动作 | DoD（完成标准） |
|---|---|---|---|---|
| P0 | 全局 `STATE` 会话共享 | 并发串会话、上下文污染 | 移除 `protobuf2openai/state.py` 的全局会话字段，改为请求级上下文或 session store(含TTL) | 并发测试（2+会话）100%无串线 |
| P0 | async 链路同步 `requests` | 阻塞事件循环、吞吐下降 | `router.py/bridge.py` 全改 `httpx.AsyncClient`，统一 client 工厂 | 压测下 p95 延迟下降且无阻塞告警 |
| P0 | `REFRESH_TOKEN_B64` 硬编码 fallback | 安全审计风险、行为不可控 | 引入 `STRICT_ENV`（默认生产开启），禁用硬编码 fallback | 生产配置缺失时启动失败并给出明确报错 |
| P1 | `server.py` 过大且职责混合 | 维护困难、易回归 | 拆为 `app/main.py` + `app/bootstrap.py` + routes | `server.py` ≤ 150 行（兼容入口） |
| P1 | `server_message_data` 重复实现 | 行为漂移风险 | 仅保留 `core/server_message_data.py` 实现，删除重复代码 | 全项目只剩一处实现 |
| P1 | 启动日志与实际路由不一致 | 运维误导 | 同步修正 endpoint 清单或补齐缺失路由 | 文档/日志/API三者一致 |
| P1 | import side effects | 测试和运行不稳定 | 禁止模块导入即执行配置/认证初始化 | 配置与依赖仅在 startup/deps 中初始化 |
| P2 | 历史兼容壳过多 | 路径混乱 | 标记兼容层并给下线计划 | `deprecated` 清单+移除时间点明确 |
| P2 | 测试结构不足 | 回归保护弱 | 增加 contract/integration/e2e 分层 | CI 中至少执行 smoke+contract |

## 2.3 最新进展（2026-02-19）
- 已完成：`model catalog` 核心实现迁移到 `src/warp2api/domain/models/model_catalog.py`，旧路径兼容文件已移除。
- 已完成：`warp request controller` 逻辑迁移到 `src/warp2api/application/services/warp_request_service.py`，旧路径文件已移除。
- 已完成：protobuf 编解码公共实现收敛到 `src/warp2api/infrastructure/protobuf/codec.py`。
- 已完成：账号池后台监控迁移到 `src/warp2api/infrastructure/monitoring/account_pool_monitor.py`，并在 bridge 启停生命周期自动启动/停止。
- 已完成：新增健康接口 `GET /api/warp/token_pool/health`。
- 已完成：`warp2protobuf/warp/service.py` 核心迁移到 `src/warp2api/application/services/token_rotation_service.py`（旧文件已移除）。
- 已完成：`warp2protobuf/warp/transport.py`、`warp2protobuf/warp/event_parser.py`、`warp2protobuf/warp/simple_proxy.py` 核心迁移到 `src/warp2api/infrastructure/*`（旧文件已移除）。
- 已完成：`protobuf2openai/*` 代码整体迁移到 `src/warp2api/adapters/{openai,anthropic,gemini}`（旧目录实现文件已移除）。
- 已完成：`warp2protobuf/api/*` 路由层迁移到 `src/warp2api/api/*`（旧目录实现文件已移除）。


## 3. 目标目录结构（建议）
```text
warp2api/
  pyproject.toml
  README.md
  src/
    warp2api/
      app/
        main.py                # FastAPI app 装配
        lifespan.py            # 启停钩子（可选）
        deps.py                # 依赖注入（可选）
      api/
        routes/
          health_routes.py
          auth_routes.py
          warp_routes.py
          openai_routes.py
        schemas/
          common.py
          warp.py
          openai.py
      adapters/
        openai/
          request_mapper.py
          response_mapper.py
          stream_mapper.py
        anthropic/
          request_mapper.py
          response_mapper.py
          stream_mapper.py
        gemini/
          request_mapper.py
          response_mapper.py
          stream_mapper.py
      application/
        services/
          warp_execution_service.py
          token_rotation_service.py
          model_capability_service.py
      domain/
        models/
          message.py
          token.py
          model_capability.py
        errors/
          common.py
      infrastructure/
        providers/
          warp_provider.py      # 上游 Warp 调用封装
        transport/
          http_client.py
          sse_parser.py
        protobuf/
          codec.py
          schemas_loader.py
        auth/
          jwt_manager.py
          refresh_provider.py
        settings/
          config.py
      observability/
        logging.py
        metrics.py             # 可选
  tests/
    unit/
    integration/
    e2e/
```


## 4. 分层职责定义

### 4.1 API 层（`api/routes`）
- 只负责：请求校验、响应序列化、HTTP 状态码映射。
- 不直接写 Warp 传输细节、不直接写 protobuf 编码细节。

### 4.2 Adapter 层（`adapters`）
- 协议映射层：`OpenAI / Anthropic / Gemini` 请求 <-> 内部命令；内部结果 <-> 各协议响应。
- 负责各“对外 API 协议”差异，不直接承担上游 Warp 调用。

### 4.3 Application 层（`application/services`）
- 编排层：执行策略、fallback、token 轮换、配额冷却、模型参数策略。
- 面向 use-case，不关心 FastAPI、http 库、具体 protobuf 实现细节。

### 4.4 Domain 层（`domain`）
- 纯业务模型和错误定义，不依赖框架。
- 承载“什么是合法模型参数/能力”的抽象与约束。

### 4.5 Infrastructure 层（`infrastructure`）
- 具体实现：上游 Warp provider、HTTP 调用、protobuf 编解码、JWT 刷新、配置加载。
- 是最“可替换”的层（实现细节隔离）。


## 5. 迁移策略（零行为变更优先）

### Phase 0：冻结行为基线
- 固化现有 smoke 测试与关键链路样例（已完成部分）。
- 新增最小集成测试：`/api/warp/send`、`/api/warp/send_stream`、`/v1/chat/completions`（mock 上游）。
- 新增并发隔离基线测试：至少 2 个并发会话，验证不共享 `conversation_id/task_id`。

### Phase 0.5：安全与阻塞快速修复（P0）
- 移除全局会话共享（先不改外部 API）。
- 替换 `requests` 为 `httpx.AsyncClient`（仅替换调用方式，不改返回结构）。
- 增加 `STRICT_ENV` 配置策略，禁用生产硬编码 token fallback。

### Phase 1：引入 `src/warp2api` 包（并行）
- 新建 `src/warp2api` 骨架，先复制不改逻辑。
- 保留老路径作为兼容导入层（thin wrapper），避免一次性大改。

### Phase 2：路由迁移
- 将现有路由入口迁移到 `src/warp2api/api/routes`。
- 老路由模块仅做 re-export，逐步下线。

### Phase 3：服务与基础设施解耦
- 把 token 轮换/冷却、fallback 策略沉到 `application/services`。
- 将 http/protobuf/auth 具体实现放到 `infrastructure`。
- 完成同步 I/O 清理：adapter/app 链路移除 `requests`。
- 完成配置安全收敛：禁用默认 `REFRESH_TOKEN_B64` 兜底（生产模式）。

### Phase 4：适配层统一
- 将 `protobuf2openai` 合并为 `adapters/openai + api/routes/openai_routes.py`。
- 预留并行扩展：`adapters/anthropic`、`adapters/gemini`。
- 统一事件解析入口，避免多处重复逻辑。

### Phase 5：清理与收敛
- 删除过时模块、统一命名规范、统一错误模型。
- 完成文档与运维脚本更新（pm2/uvicorn 启动点更新）。
- 输出兼容层下线公告：哪些路径仍可用、哪些将在何时移除。


## 6. 命名与边界规范
- 路由文件命名：`*_routes.py`
- 服务文件命名：`*_service.py`
- 适配文件命名：`*_mapper.py`
- 基础设施实现：`*_client.py` / `*_manager.py` / `codec.py`
- 禁止跨层逆向依赖：
  - `api` 可依赖 `application`/`adapters`
  - `application` 可依赖 `domain` 与抽象接口
  - `infrastructure` 不依赖 `api`


## 7. 测试策略
- `tests/unit`：domain + service 纯逻辑测试（无网络）。
- `tests/integration`：api + service + infrastructure（mock 上游 Warp）。
- `tests/e2e`：可选，真实环境验证（需 token/网络）。
- 每次迁移 phase 至少保证：
  - 所有 smoke 通过
  - 非法模型 ID 返回 400（不兜底）
  - token pool 状态接口可用
  - 并发会话隔离验证通过（无跨请求状态污染）

## 7.1 新增契约测试要求（adapter 维度）
- OpenAI adapter：
  - 非流式/流式输出结构符合 OpenAI Chat Completions。
  - tool_calls 结构字段稳定（id/type/function）。
- Anthropic adapter：
  - `messages` 与 `content block` 输出结构稳定。
- Gemini adapter：
  - `generateContent` 与 `streamGenerateContent` 基础结构稳定。

## 7.2 并发与性能基线
- 并发隔离：
  - 至少 20 并发请求，验证 conversation/task 不串线。
- 性能基线（开发环境）：
  - 修复前后对比：p50/p95 延迟、错误率、超时率。
- 事件循环健康：
  - 不允许在核心 async 路由中出现同步网络 I/O。


## 8. 配置与运行规范
- 统一配置入口：`infrastructure/settings/config.py`（基于环境变量）。
- 逐步将散落配置收敛到单配置对象。
- 启动入口统一为：
  - `python -m warp2api.app.main`
  - 或 `uvicorn warp2api.app.main:app`


## 9. 风险与回滚
- 风险：
  - 导入路径变更导致运行时找不到模块
  - 路由迁移时响应结构细节变化
  - adapter 迁移时 SSE 事件映射回归
- 控制：
  - 每 phase 保留旧入口兼容层
  - 每 phase 后运行 smoke + 关键集成测试
- 回滚：
  - 使用 Git 按 phase 回滚（不做跨 phase 混合提交）


## 10. 验收标准
- 目录结构切换到 `src/warp2api`，旧目录仅保留兼容薄层或移除。
- `protobuf2openai` 与 `warp2protobuf` 的核心逻辑收敛到统一分层。
- 核心端点行为一致，已有调用方无感升级。
- 至少具备：
  - smoke 测试集
  - 关键链路集成测试
  - adapter 契约测试（OpenAI/Anthropic/Gemini）
  - 并发会话隔离测试
  - 清晰架构文档与运行说明

## 10.1 协议兼容现状（2026-02-19）
- OpenAI:
  - 已支持：`GET /v1/models`、`POST /v1/chat/completions`、`POST /v1/responses`（含基础 stream 事件）
  - 备注：`usage` 当前为占位统计（非真实 token 计费值）
- Anthropic:
  - 已支持：`POST /v1/messages`（基础兼容，含 stream）
  - 已增加关键校验：`anthropic-version`、`model`、`max_tokens`
- Gemini:
  - 已支持：`v1` 与 `v1beta` 的 `generateContent / streamGenerateContent`

仍待增强：
- OpenAI Responses 的完整事件矩阵与多模态输入细节。
- 更精确的 usage/token 统计（如需，需引入额外 tokenizer 或上游计量字段）。


## 11. 下一步执行建议
1. 先执行 Phase 0.5（P0）：会话隔离 + async I/O + 配置安全。
2. 再执行 Phase 1/2：创建 `src/warp2api` 骨架并迁移路由（保留兼容导出）。
3. 在 Phase 3 收口 P1：服务/基础设施解耦、重复实现收敛、去 import 副作用。
4. 最后 Phase 5：兼容层下线计划与运维文档收口。

## 12. 当前执行进度（2026-02-19）
- Phase 0.5：已完成
  - 全局会话状态污染修复
  - async 链路移除 `requests`
  - `STRICT_ENV` 与配置安全校验生效
- Phase 1：已完成（骨架）
  - 已引入 `src/warp2api` 包结构
  - 已提供统一启动入口：`warp2api` / `warp2api-bridge` / `warp2api-openai`
  - 旧入口保持兼容：`server.py`、`openai_compat.py`（已降级为 thin wrapper）
- Phase 2：已部分完成
  - 运行时主实现已迁移到：
    - `src/warp2api/app/bridge_runtime.py`
    - `src/warp2api/app/openai_runtime.py`
  - 旧入口仅保留兼容导出，避免破坏现有脚本/部署
  - bridge 侧 app 组装已迁移到：
    - `src/warp2api/app/bridge_app.py`
    - `src/warp2api/app/bridge_bootstrap.py`
  - bridge 启动流程已切换为 `lifespan`（去 `on_event`）
- 协议兼容增强：已完成一轮
  - OpenAI `POST /v1/responses`（基础兼容）
  - Anthropic 关键 header/字段校验
  - Gemini `v1beta` 路径兼容
- 工程化：已补齐基础 CI
  - `.github/workflows/ci.yml` 执行编译检查 + pytest
