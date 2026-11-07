# 共享契约与并行开发计划

## 四项目并行策略

建议四个 Codex 按以下顺序并行：

- Codex A：`user-server`，先完成认证、积分、模型读取、任务创建接口 mock。
- Codex B：`admin-server`，先完成管理员认证、用户管理、充值档位、模型和价格配置。
- Codex C：`user-web`，基于本文档 API contract 先用 mock service 开发页面，再切真实接口。
- Codex D：`admin-web`，基于本文档 API contract 先用 mock service 开发表格/表单，再切真实接口。

并行约束：

- 两个前端不得等待后端完成才能开始，先建立 typed API client 和 mock data。
- 两个后端先统一 migration 命名和表 ownership，避免重复建表。
- 所有接口字段变更必须同步更新本文件。
- 后端接口返回统一格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

错误返回：

```json
{
  "code": 40001,
  "message": "余额不足",
  "data": null
}
```

## 枚举

### WorkType

- `image_edit`
- `text_to_image`
- `batch_generate`
- `batch_edit`
- `product_model_try_on`
- `product_multi_view`
- `product_pose`
- `product_ootd`
- `product_background_replace`
- `product_scene_compose`

### CreditBizType

- `recharge`
- `image_task`
- `refund`
- `admin_adjustment`
- `signin`
- `invite`

### ImageTaskStatus

- `pending`
- `queued`
- `running`
- `succeeded`
- `failed`
- `refunded`

### RechargeOrderStatus

- `pending`
- `paid`
- `expired`
- `cancelled`
- `failed`

## 用户端关键 DTO

### AuthUser

```ts
type AuthUser = {
  id: number;
  username: string;
  email: string;
  nickname?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
};
```

### CreditBalance

```ts
type CreditBalance = {
  balance: number;
  total_recharged: number;
  total_consumed: number;
};
```

### RechargePlan

```ts
type RechargePlan = {
  id: number;
  name: string;
  amount_cents: number;
  credit_amount: number;
  bonus_credit_amount: number;
  total_credit_amount: number;
  badge?: string | null;
  is_recommended: boolean;
};
```

### ImageModel

```ts
type ImageSpecOption = {
  id?: number;
  value: string;
  code?: string;
  label: string;
};

type ImageModel = {
  id: number;
  name: string;
  code: string;
  work_type: string;
  description: string;
  is_recommended: boolean;
  is_stable: boolean;
  is_new: boolean;
  speed_hint?: string | null;
  risk_hint?: string | null;
  max_input_images: number;
  max_output_images: number;
  supported_resolutions: ImageSpecOption[];
  supported_aspect_ratios: ImageSpecOption[];
};

type ModelOption = {
  value: string;
  label: string;
};
```

### Image Specs

图片规格是平台主数据，由 admin-server 管理，user-server 只读取已启用规格。

```ts
type ImageSpec = {
  id: number;
  code: string;
  label: string;
  sort_order: number;
  is_active: boolean;
};

type ImageSpecs = {
  resolutions: ImageSpec[];
  aspect_ratios: ImageSpec[];
};
```

模型必须通过关联表声明支持的分辨率和尺寸。启用模型前必须存在所有 `work_type x resolution x aspect_ratio x output_count=1` 的 active 价格组合。

### ImageTask

```ts
type ImageTask = {
  id: number;
  task_no: string;
  work_type: string;
  model_id: number;
  model_name: string;
  prompt: string;
  resolution: string;
  aspect_ratio: string;
  credit_cost: number;
  status: ImageTaskStatus;
  failure_message?: string | null;
  input_images: ImageAsset[];
  output_images: ImageAsset[];
  created_at: string;
  finished_at?: string | null;
};

type ImageAsset = {
  id: number;
  url: string;
  width: number;
  height: number;
  mime_type: string;
  size_bytes: number;
};
```

## 管理端关键 DTO

### AdminUser

```ts
type AdminUser = {
  id: number;
  username: string;
  email: string;
  role: "super_admin" | "operator" | "finance" | "model_admin";
  is_active: boolean;
};
```

### ManagedUser

```ts
type ManagedUser = {
  id: number;
  username: string;
  email: string;
  nickname?: string | null;
  is_active: boolean;
  credit_balance: number;
  created_at: string;
  last_login_at?: string | null;
};
```

### AdminImageModel

```ts
type AdminImageModel = {
  id: number;
  provider_id: number;
  provider_name: string;
  name: string;
  code: string;
  vendor_model: string;
  work_type: string;
  description: string;
  base_url_masked?: string;
  api_key_masked?: string;
  is_recommended: boolean;
  is_stable: boolean;
  is_new: boolean;
  max_input_images: number;
  max_output_images: number;
  is_active: boolean;
  supported_resolutions: ImageSpec[];
  supported_aspect_ratios: ImageSpec[];
  updated_at: string;
};
```

用户端报价接口：

- `POST /models/{model_id}/quote`
- 入参：`work_type`、`resolution`、`aspect_ratio`、`output_count`
- 出参：`credit_cost`，以及实际命中的 `work_type`

### ModelPrice

```ts
type ModelPrice = {
  id: number;
  model_id: number;
  model_name: string;
  work_type: string;
  resolution: string;
  aspect_ratio: string;
  output_count: number;
  credit_cost: number;
  version: number;
  effective_at: string;
  is_active: boolean;
  change_reason: string;
};
```

## 关键业务规则

### 扣积分

- 前端展示的预计消耗只作提示。
- 后端创建任务时重新计算价格。
- 扣积分和创建任务在一个事务中完成。
- 余额不足返回业务错误，不创建任务。

### 退款

- 自动退款只处理明确失败且未产出结果的任务。
- 人工退款由 admin-server 发起，必须写原因。
- 同一个任务只能退款一次，依赖幂等键防重。

### 价格变更

- `image_model_prices` 不允许覆盖历史。
- 新价格 active 后，旧 active 价格停用。
- `image_tasks.price_snapshot` 保存任务创建时的价格。

### 模型配置变更

- 停用模型后不能创建新任务。
- 已创建任务继续按快照执行。
- 配置保存后写 Redis 版本号，例如 `model_config_version`，user-server 读取时发现版本变化则刷新缓存。

## 数据库 ownership

为避免两个后端重复 migration：

- `user-server` owns：
  - `users`
  - `user_credit_accounts`
  - `credit_ledger`
  - `recharge_orders`
  - `image_assets`
  - `image_tasks`
  - `works`
- `admin-server` owns：
  - `admin_users`
  - `recharge_plans`
  - `image_model_providers`
  - `image_models`
  - `image_resolution_specs`
  - `image_aspect_ratio_specs`
  - `image_model_resolutions`
  - `image_model_aspect_ratios`
  - `image_model_prices`
  - `model_test_runs`
  - `admin_audit_logs`

跨服务读取对方 owns 的表可以，但不要在自己的 migration 中重复定义创建。

## 第一阶段里程碑

### M1 可登录和可配置

- user-server：用户注册登录、积分账户。
- admin-server：管理员登录、充值档位、模型、价格配置。
- user-web：登录注册、基础布局。
- admin-web：登录、后台布局、配置页面 mock。

### M2 可充值和可创建任务

- user-server：充值 mock 支付、模型列表、报价、任务创建、mock 模型执行。
- admin-server：用户积分管理、模型测试。
- user-web：充值弹窗、图片编辑工作台。
- admin-web：用户管理、积分流水、模型测试 UI。

### M3 可真实调用模型和作品管理

- user-server：真实模型适配、上传存储、结果保存。
- admin-server：失败任务退款/重试、审计完整。
- user-web：作品流、继续编辑、我的作品。
- admin-web：任务管理、审计日志。

### M4 生产加固

- 并发扣费测试。
- 支付回调幂等测试。
- 模型失败退款测试。
- 大列表分页和索引检查。
- 密钥加密和脱敏检查。
- 部署文档和环境变量审计。
