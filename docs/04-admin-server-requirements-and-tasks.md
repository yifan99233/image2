# admin-server 管理端服务需求与开发任务

## 项目定位

`admin-server` 是平台管理服务，负责管理员认证、用户管理、积分调整、充值档位配置、图片模型配置、模型价格配置、模型测试、任务管理、审计日志。它和 `user-server` 共享数据库，但只暴露 `/admin/**` 接口。

## 核心职责

- 管理员登录和权限校验。
- 用户查询、禁用、密码重置。
- 人工积分加减和流水审计。
- 充值档位管理。
- 模型连接配置管理，敏感字段加密存储。
- 模型能力和消耗积分配置管理。
- 模型连通性测试。
- 图片任务查询、失败任务退款/重试。
- 管理员审计日志。
- 配置变更后通知 Redis 缓存失效。

## 认证与权限

- 管理员可复用 `users` 表，也可单独建 `admin_users`。第一版建议单独建 `admin_users`，避免普通用户和后台人员权限混杂。
- 管理员密码、RSA 登录、JWT 签发方式参考 `testflow3.0`。
- 管理 JWT 和用户 JWT 使用不同 `audience` 或不同 `SECRET_KEY`。
- 权限第一版至少支持：
  - `super_admin`
  - `operator`
  - `finance`
  - `model_admin`
- 客户归属修改使用独立权限 `users:ownership:write`，默认仅授予 `super_admin` 和 `operator`；可分配的归属对象是当前站点的启用后台账号。
- 所有写操作必须记录审计日志。

## 数据模型

### admin_users

- `id`
- `username`
- `email`
- `password_hash`
- `role`
- `is_active`
- `last_login_at`
- `created_at`
- `updated_at`

### users 客户归属

- `customer_owner_admin_id`：负责该客户的后台账号 ID，可为空；修改必须校验站点范围并写入审计日志。

### recharge_plans

- `id`
- `name`
- `amount_cents`
- `credit_amount`
- `bonus_credit_amount`
- `badge`
- `description`
- `sort_order`
- `is_recommended`
- `is_active`
- `created_by`
- `updated_by`
- `created_at`
- `updated_at`
- `deleted_at`

### image_model_providers

- `id`
- `name`
- `code`
- `base_url`
- `auth_type`
- `encrypted_api_key`
- `timeout_seconds`
- `retry_count`
- `is_active`
- `created_at`
- `updated_at`

### image_models

- `id`
- `provider_id`
- `name`
- `code`
- `vendor_model`
- `work_type`
- `description`
- `is_recommended`
- `is_stable`
- `is_new`
- `speed_hint`
- `risk_hint`
- `max_input_images`
- `max_output_images`
- `sort_order`
- `is_active`
- `created_at`
- `updated_at`
- `deleted_at`

### image_model_options

- `id`
- `model_id`
- `option_type`：`resolution` / `aspect_ratio` / `output_count`
- `option_value`
- `label`
- `sort_order`
- `is_active`

### image_model_prices

- `id`
- `model_id`
- `work_type`
- `resolution`
- `aspect_ratio`
- `output_count`
- `credit_cost`
- `version`
- `effective_at`
- `change_reason`
- `is_active`
- `created_by`
- `created_at`

要求：

- 新价格用新版本，不覆盖历史。
- 同一模型同一维度只能有一个 active 价格。

### model_test_runs

- `id`
- `model_id`
- `admin_user_id`
- `prompt`
- `input_asset_id`
- `status`
- `duration_ms`
- `request_summary`
- `response_summary`
- `error_message`
- `created_at`

### admin_audit_logs

- `id`
- `admin_user_id`
- `action`
- `resource_type`
- `resource_id`
- `before_snapshot`
- `after_snapshot`
- `reason`
- `ip`
- `user_agent`
- `created_at`

## 管理端 API

### 认证

- `GET /admin/auth/public-key`
- `POST /admin/auth/login`
- `GET /admin/auth/me`
- `PATCH /admin/auth/me/password`

### 控制台

- `GET /admin/dashboard/metrics`

### 用户管理

- `GET /admin/users`
- `GET /admin/users/{user_id}`
- `PATCH /admin/users/{user_id}/status`
- `PATCH /admin/users/{user_id}/password`
- `POST /admin/users/{user_id}/credit-adjustments`

### 积分

- `GET /admin/credits/ledger`
- `POST /admin/credits/ledger/{ledger_id}/mark`

### 充值档位

- `GET /admin/recharge/plans`
- `POST /admin/recharge/plans`
- `PATCH /admin/recharge/plans/{plan_id}`
- `PATCH /admin/recharge/plans/{plan_id}/status`
- `DELETE /admin/recharge/plans/{plan_id}`

### 模型

- `GET /admin/model-providers`
- `POST /admin/model-providers`
- `PATCH /admin/model-providers/{provider_id}`
- `GET /admin/models`
- `POST /admin/models`
- `PATCH /admin/models/{model_id}`
- `PATCH /admin/models/{model_id}/status`
- `POST /admin/models/{model_id}/test`
- `GET /admin/models/{model_id}/test-runs`

### 模型价格

- `GET /admin/model-prices`
- `POST /admin/model-prices`
- `PATCH /admin/model-prices/{price_id}/status`

### 任务

- `GET /admin/image-tasks`
- `GET /admin/image-tasks/{task_id}`
- `POST /admin/image-tasks/{task_id}/refund`
- `POST /admin/image-tasks/{task_id}/retry`

### 审计

- `GET /admin/audit-logs`

## 开发任务

### T1 服务基础

- 初始化 FastAPI 项目。
- 配置 async SQLAlchemy、Alembic、PostgreSQL、Redis。
- 实现统一响应、异常、日志、配置。
- 实现 `/healthz`。

验收：

- 本地服务可启动。
- migration 可创建 admin 相关表。

### T2 管理员认证和权限

- 实现 `admin_users`。
- 实现 RSA 登录、JWT、当前管理员依赖。
- 实现权限依赖。
- 初始化超级管理员 seed 脚本。

验收：

- 超级管理员可登录。
- 禁用管理员不能登录。
- 无权限访问返回 403。

### T3 审计日志基础

- 实现 `admin_audit_logs`。
- 实现审计装饰器或服务方法。
- 所有写接口接入审计。

验收：

- 创建/修改/停用配置都有 before/after 快照。
- 人工积分调整记录原因。

### T4 用户管理

- 实现用户列表、详情。
- 实现启用/禁用、重置密码。
- 实现人工积分调整，复用 `credit_ledger` 幂等服务。

验收：

- 人工扣减不能导致负余额。
- 所有调整写积分流水和审计日志。

### T5 充值档位配置

- 实现档位 CRUD。
- 实现上下架、软删除、排序。
- 实现配置缓存失效。

验收：

- 已被订单引用的档位不能物理删除。
- 用户端只看到 active 档位。

### T6 模型和供应商配置

- 实现 provider CRUD，API key 加密存储。
- 实现 model CRUD。
- 实现 model options 管理。
- 实现启用/停用和排序。

验收：

- API key 返回脱敏。
- 停用模型后用户端模型列表不可见。

### T7 模型测试

- 实现模型测试接口。
- 支持测试图片上传或引用已有图片。
- 调用模型客户端抽象并记录 `model_test_runs`。
- 返回耗时、状态、错误摘要。

验收：

- base URL/API key 错误能返回可读错误。
- 测试记录可查询。

### T8 模型价格配置

- 实现价格列表。
- 实现新增价格版本。
- 新增 active 价格时停用同维度旧 active 价格。
- 价格变更写审计并失效用户端缓存。

验收：

- 历史价格记录保留。
- 新任务使用最新 active 价格。

### T9 任务管理

- 实现任务列表和详情。
- 实现失败任务人工退款。
- 实现失败任务重试。
- 重试必须创建新任务或新 attempt，不能覆盖原任务历史。

验收：

- 退款幂等。
- 重试记录能追溯原任务。

### T10 测试和质量

- 单元测试：权限、审计、价格版本、密钥脱敏、积分调整。
- 集成测试：管理员登录、档位配置、模型配置、价格配置、人工退款。
- 补 README、环境变量、部署说明。
