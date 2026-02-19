# Token 管理与 UI 规划方案（参考 all-2-api）

## 1. 目标

为 `warp2api` 增加一套可运维的 Warp refresh token 账号池系统，支持：

- 手动上传/批量导入 refresh token
- 账号健康状态跟踪（可用、冷却、封禁、配额不足）
- 自动轮询与故障转移
- 管理 UI（查看状态、手动操作、审计）

## 2. 参考项目调研结论（all-2-api）

调研路径：

- `src/warp/warp-routes.js`
- `src/warp/warp-service.js`
- `src/db.js`（`warp_credentials` 相关）
- `src/public/pages/warp.html`

### 2.1 可借鉴点

- 有完整管理 API：
  - `/api/warp/credentials`
  - `/api/warp/statistics`
  - `/api/warp/credentials/:id/refresh`
  - `/api/warp/credentials/batch-import`
  - `/api/warp/health`
- 账号池字段较完整：
  - `is_active`, `error_count`, `last_error_*`, `use_count`, `quota_limit`, `quota_used`
- 有批量操作能力：
  - 批量导入、批量 refresh、批量配额刷新
- 有前端运维界面（`warp.html`）：
  - 统计卡片、账号卡片、单账号操作、批量导入
- 有基本故障转移：
  - 请求失败后尝试下一个可用账号

### 2.2 不建议直接照搬的点

- token 明文存储/展示策略过宽（需要改成加密存储 + mask 展示）
- 业务内通过 `curl` shell 刷新 token（应统一为 HTTP client）
- 失败状态以 `error_count` 阈值硬编码判定，状态语义不够清晰
- UI 与业务逻辑耦合在单页面内联脚本，维护成本高

## 3. 适配到当前 warp2api 的目标架构

遵循现有分层（`adapters -> application -> infrastructure`）：

- `adapters`: 管理端 API + 管理页面
- `application`: token 池策略、状态机、调度、健康检查编排
- `infrastructure`: token 仓储、加密、外部调用（refresh/quota）

## 4. 领域模型设计

建议新增 `TokenAccount`：

- `id`
- `label`
- `token_hash`（唯一）
- `refresh_token_encrypted`
- `status`：
  - `active`
  - `cooldown`
  - `blocked`
  - `quota_exhausted`
  - `disabled`
- `error_count`
- `last_error_code`
- `last_error_message`
- `last_success_at`
- `last_check_at`
- `cooldown_until`
- `use_count`
- `quota_limit`
- `quota_used`
- `quota_updated_at`
- `created_at`
- `updated_at`

## 5. 状态机与调度策略

### 5.1 状态转换

- 成功请求：`* -> active`（清理错误计数）
- 429/限流：`active -> cooldown`（短冷却）
- 配额耗尽：`active -> quota_exhausted`（长冷却或人工恢复）
- 403 封禁：`active -> blocked`（人工确认恢复）
- 手动禁用：`* -> disabled`

### 5.2 选号策略

- 候选集：`active` 且未冷却
- 排序键：
  1. `error_count` 升序
  2. `last_success_at` 降序
  3. `use_count` 升序
- 单账号加锁，避免并发踩同一 token

## 6. 管理 API 设计（MVP）

- `GET /admin/tokens`
- `GET /admin/tokens/{id}`
- `POST /admin/tokens`
- `POST /admin/tokens/batch-import`
- `PATCH /admin/tokens/{id}`（label/status）
- `POST /admin/tokens/{id}/refresh`
- `POST /admin/tokens/{id}/health-check`
- `POST /admin/tokens/refresh-all`
- `GET /admin/tokens/statistics`
- `GET /admin/tokens/events`

约束：

- 返回中永不输出完整 refresh token，只返回 `prefix...suffix`
- 管理接口单独鉴权（`ADMIN_TOKEN`）

## 7. UI 设计（MVP）

页面：`/admin/tokens`

- 顶部统计：
  - 总数、active、cooldown、blocked、quota_exhausted
- 列表/卡片：
  - label、status、error_count、last_success、quota、cooldown 剩余
- 操作：
  - 添加、批量导入、启停、单个 refresh、健康检查、批量 refresh
- 详情抽屉：
  - 最近错误、最近健康检查记录、审计日志

技术建议：

- 第一版可用 FastAPI 模板 + 原生 JS（不引入重前端框架）
- UI 逻辑不要内联到 HTML，拆到 `static/js/admin-tokens.js`

## 8. 数据与安全

- refresh token 使用应用密钥加密后落库（AES-GCM）
- 记录 `token_hash` 防重复导入
- 所有管理操作写审计日志：
  - 操作人、动作、目标 token、结果、时间

## 9. 部署建议

### 9.1 首选：服务器常驻部署

原因：

- 需要后台健康检查任务
- 需要流式请求稳定性（SSE）
- 需要常驻状态调度（冷却、故障转移）

建议：

- `uvicorn + pm2/systemd + nginx`
- SQLite（先行方案，降低部署复杂度）
- Redis（可选：仅在高并发/多进程抢占明显时引入）

SQLite 细节（MVP 强制）：

- 启用 WAL：`PRAGMA journal_mode=WAL`
- 适当同步级别：`PRAGMA synchronous=NORMAL`
- token 密文存储（AES-GCM）
- 审计日志独立表（append-only）

### 9.2 Serverless 仅建议拆分混合方案

- 管理 UI/API 可放 serverless
- 核心 Warp 流式代理与健康检查仍建议常驻服务

> 当前决策：先不走 serverless，采用单机/单服务部署。

## 10. 单通道架构守卫（必须执行）

唯一上游发送通道：

- `token_rotation_service.send_protobuf_with_rotation(...)`

硬性规则：

- OpenAI / Anthropic / Gemini 最终都必须落到该通道
- 禁止新增 `httpx -> 本地 /api/warp/send_stream -> 再转发` 平行链路
- 诊断端点允许存在，但不能成为业务主链路依赖
- 新代码评审中，将此项作为阻断条件

## 11. 分阶段实施计划

### Phase 1（后端基础）

- 新建 token 表和 repository
- 实现 CRUD + batch import + statistics
- 接入 `application/services/token_pool_service.py`
- 增加 `ADMIN_TOKEN` 鉴权中间层（仅 `/admin/*`）
- SQLite 初始化脚本（含 WAL pragma 与 migration 版本表）
- 审计日志表与统一审计写入接口
- 完成最小可用 API：
  - `GET /admin/tokens`
  - `POST /admin/tokens/batch-import`
  - `PATCH /admin/tokens/{id}`
  - `POST /admin/tokens/{id}/refresh`
  - `GET /admin/tokens/statistics`

### Phase 2（运行时接管）

- 主请求路径改为账号池选号
- 失败分类与状态机落地
- 加入单账号并发锁

### Phase 3（健康检查）

- 后台周期任务
- 更新配额与健康状态
- 暴露健康快照 API

### Phase 4（管理 UI）

- 新增 `/admin/tokens` 页面
- 列表 + 操作 + 审计视图

### Phase 5（硬化）

- token 加密存储
- 管理权限与审计完善
- 限流与防暴力策略

## 12. 验收标准

- 可手动导入/批量导入 token
- 请求链路支持自动故障转移
- UI 可实时看到账号状态与错误原因
- 403/quota/429 三类错误可区分并自动进入对应状态
- 并发下不会重复使用同一 token 造成状态竞争
