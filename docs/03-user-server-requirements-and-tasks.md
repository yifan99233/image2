# user-server 用户端服务需求与开发任务

## 项目定位

`user-server` 是用户端业务服务，提供账号、积分余额、充值订单、模型读取、图片上传、图片 AI 任务、作品管理等接口。它只能读取后台发布的模型和价格配置，不能提供配置写接口。

## 核心职责

- 用户注册、登录、当前用户信息、密码修改。
- 用户积分余额查询、积分流水查询。
- 充值档位查询、充值订单创建、支付状态查询。
- 已启用模型列表查询、模型能力选项查询。
- 图片上传和文件访问授权。
- 图片任务创建、扣积分、调用模型、任务状态查询。
- 作品列表、采集、推荐、删除、下载导出。
- Redis 限流、登录失败保护、任务状态缓存。

## 认证与安全

- 参考 `/Users/apple/work/testflow3.0/Server/app/services/security.py` 实现密码哈希、校验、JWT 签发和验证。
- 参考 `/Users/apple/work/testflow3.0/Server/app/api/endpoints/auth.py` 实现 `/auth/public-key`、`/auth/register`、`/auth/login`、`/auth/me`。
- 生产环境必须要求前端 RSA 加密密码；明文降级只允许本地开发配置开启。
- 用户只能访问自己的订单、流水、任务和作品。
- 上传文件必须校验 MIME、扩展名、大小、图片维度。
- 模型 API key 不允许出现在用户端任何响应里。

## 数据模型

用户端服务需要读写以下表。字段以 SQLAlchemy/Alembic migration 为准。

### users

- `id`
- `username`
- `email`
- `password_hash`
- `nickname`
- `avatar_url`
- `is_active`
- `last_login_at`
- `created_at`
- `updated_at`
- `deleted_at`

索引：

- `uq_users_email`
- `idx_users_active_created`

### user_credit_accounts

- `id`
- `user_id`
- `balance`
- `total_recharged`
- `total_consumed`
- `version`
- `created_at`
- `updated_at`

要求：

- `user_id` 唯一。
- 扣减积分时使用行锁或乐观锁，不能出现负余额。

### credit_ledger

- `id`
- `user_id`
- `account_id`
- `direction`：`credit` / `debit`
- `amount`
- `balance_before`
- `balance_after`
- `biz_type`：`recharge` / `image_task` / `refund` / `admin_adjustment` / `signin` / `invite`
- `biz_id`
- `idempotency_key`
- `description`
- `operator_type`：`user` / `admin` / `system`
- `operator_id`
- `created_at`

索引：

- `uq_credit_ledger_idempotency_key`
- `idx_credit_ledger_user_created`
- `idx_credit_ledger_biz`

### recharge_orders

- `id`
- `order_no`
- `user_id`
- `plan_id`
- `amount_cents`
- `credit_amount`
- `bonus_credit_amount`
- `status`：`pending` / `paid` / `expired` / `cancelled` / `failed`
- `payment_provider`
- `provider_trade_no`
- `pay_url`
- `qr_code_url`
- `paid_at`
- `expires_at`
- `created_at`
- `updated_at`

### image_tasks

- `id`
- `task_no`
- `user_id`
- `work_type`
- `model_id`
- `model_snapshot`
- `price_snapshot`
- `prompt`
- `negative_prompt`
- `resolution`
- `aspect_ratio`
- `input_image_ids`
- `output_count`
- `credit_cost`
- `status`：`pending` / `queued` / `running` / `succeeded` / `failed` / `refunded`
- `failure_code`
- `failure_message`
- `provider_request_id`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

索引：

- `idx_image_tasks_user_created`
- `idx_image_tasks_status_created`
- `idx_image_tasks_model_created`

### image_assets

- `id`
- `user_id`
- `storage_key`
- `url`
- `mime_type`
- `width`
- `height`
- `size_bytes`
- `sha256`
- `source`：`upload` / `model_output`
- `created_at`

### works

- `id`
- `user_id`
- `task_id`
- `category`
- `prompt_snapshot`
- `cover_asset_id`
- `input_asset_ids`
- `output_asset_ids`
- `is_collected`
- `is_recommended`
- `deleted_at`
- `created_at`
- `updated_at`

## 用户端 API

### 账号

- `GET /auth/public-key`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `PATCH /auth/me/password`

### 积分

- `GET /credits/balance`
- `GET /credits/ledger?page=&page_size=&biz_type=&start_at=&end_at=`

### 充值

- `GET /recharge/plans`
- `POST /recharge/orders`
- `GET /recharge/orders/{order_id}`
- `POST /payments/webhooks/{provider}`：支付回调，必须验签和幂等。

### 模型读取

- `GET /models?work_type=`
- `GET /models/{model_id}/options`
- `POST /models/{model_id}/quote`：根据分辨率、比例、张数返回预计积分。

### 上传

- `POST /uploads/images`
- `GET /uploads/images/{asset_id}/signed-url`

### 图片任务

- `POST /image-tasks`
- `GET /image-tasks`
- `GET /image-tasks/{task_id}`
- `POST /image-tasks/{task_id}/continue`

### 作品

- `GET /works`
- `GET /works/{work_id}`
- `PATCH /works/{work_id}`
- `DELETE /works/{work_id}`
- `POST /works/batch-export`

## 图片任务流程

1. 校验用户、模型、能力、上传图片、提示词、分辨率、比例。
2. 读取当前启用价格配置并生成 `price_snapshot`。
3. 数据库事务内创建 `image_tasks`，扣减积分，写 `credit_ledger`。
4. 提交异步执行任务，状态从 `pending` 到 `queued`。
5. Worker 调用模型供应商，状态变为 `running`。
6. 保存输出图片资产，创建或更新 `works`，状态变为 `succeeded`。
7. 如果模型调用失败：
   - 可明确失败且未产生有效结果时自动退款，写 refund 流水。
   - 不确定状态进入 `failed`，标记 `refund_pending` 由后台处理。

## 开发任务

### T1 服务基础

- 初始化 FastAPI 项目。
- 配置 async SQLAlchemy、Alembic、PostgreSQL、Redis。
- 实现统一配置、日志、异常、响应结构。
- 实现健康检查 `/healthz`。

验收：

- 本地可启动。
- 能连接 PG 和 Redis。
- Alembic 可创建初始表。

### T2 认证模块

- 实现用户模型和 migration。
- 实现密码哈希、RSA 公钥、登录、注册、JWT。
- 实现 `get_current_user` 依赖。
- 实现登录限流。

验收：

- 注册后可登录。
- 禁用用户不能登录。
- JWT 过期返回 401。

### T3 积分账户和流水

- 实现 `user_credit_accounts`、`credit_ledger`。
- 注册用户时创建积分账户。
- 实现余额查询和流水查询。
- 实现内部积分变更服务：加、扣、退，全部幂等。

验收：

- 并发扣积分不会扣成负数。
- 每次余额变化都有流水。
- 幂等键重复不会重复入账。

### T4 充值订单

- 实现充值档位读取。
- 实现订单创建。
- 实现支付 provider 抽象，第一版可提供 mock provider。
- 实现支付回调验签、订单状态更新、积分到账。

验收：

- 同一支付回调重复调用只到账一次。
- 订单过期后不能支付到账。

### T5 模型配置读取和报价

- 读取 admin-server 维护的启用模型、能力、价格。
- 实现模型列表、模型选项、报价接口。
- 对模型配置做 Redis 缓存，后台更新后可失效。

验收：

- 停用模型不返回。
- 无价格配置不能提交任务。

### T6 图片上传和资产

- 实现图片上传。
- 实现 StorageProvider 抽象：本地开发 local，生产可接 MinIO/S3。
- 记录图片宽高、大小、hash。
- 实现签名 URL 或受控访问。

验收：

- 非图片、超大文件、超限制数量会被拒绝。
- 上传后能被任务引用。

### T7 图片任务执行

- 实现任务创建、扣积分、状态查询。
- 实现模型调用客户端抽象。
- 实现异步执行和轮询状态。
- 实现成功保存结果图和作品。
- 实现失败退款策略。

验收：

- 成功任务生成作品。
- 失败任务按策略退还积分或进入后台处理。
- 任务创建和扣积分事务一致。

### T8 作品管理

- 实现作品列表、详情、采集、推荐标记、删除。
- 实现批量导出任务接口。
- 实现下载权限校验。

验收：

- 用户不能访问他人作品。
- 删除为软删除。

### T9 测试和质量

- 单元测试：密码、JWT、积分服务、价格报价、幂等。
- 集成测试：注册登录、充值到账、任务扣费退款。
- 压测关注：任务创建、作品列表、积分扣减。
- 补 README、环境变量、部署说明。
