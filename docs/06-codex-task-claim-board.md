# Codex 并行任务认领板

## 使用方式

这份文件给多个 Codex 并行开发时使用。每个 Codex 进入仓库后先阅读：

1. `docs/00-product-architecture.md`
2. `docs/05-shared-contracts-and-parallel-plan.md`
3. 自己要认领项目对应的需求任务文档
4. 本文件

认领任务时必须遵守：

- 一次只认领一个任务包。
- 认领后把 `负责人` 从 `未认领` 改成自己的编号，例如 `Codex1`、`Codex2`。
- 开始开发前先创建对应项目目录，例如 `user-server/`、`admin-server/`、`user-web/`、`admin-web/`。
- 不要改其他 Codex 已认领任务的代码，除非先在文档里写清楚需要协作的接口变化。
- 涉及共享 API、DTO、数据库字段变化时，必须同步更新 `docs/05-shared-contracts-and-parallel-plan.md`。
- 每个任务完成后，把状态改成 `完成`，并写清楚交付文件和验证命令。

状态可选：

- `未开始`
- `进行中`
- `阻塞`
- `完成`

## 推荐认领策略

如果只开两个 Codex：

- `Codex1` 优先认领服务端：`user-server` + `admin-server` 的基础能力。
- `Codex2` 优先认领前端：`user-web` + `admin-web` 的基础页面和 mock client。

如果开四个 Codex：

- `Codex1`：`user-server`
- `Codex2`：`admin-server`
- `Codex3`：`user-web`
- `Codex4`：`admin-web`

## 任务包总览

| 任务包 | 项目 | 状态 | 负责人 | 依赖 | 需求文档 |
| --- | --- | --- | --- | --- | --- |
| US-01 服务基础与认证 | user-server | 完成 | Codex1 | 无 | `docs/03-user-server-requirements-and-tasks.md` |
| US-02 积分账户与充值订单 | user-server | 未开始 | 未认领 | US-01 | `docs/03-user-server-requirements-and-tasks.md` |
| US-03 模型读取、报价、上传资产 | user-server | 未开始 | 未认领 | US-01, AS-03 | `docs/03-user-server-requirements-and-tasks.md` |
| US-04 图片任务执行与作品管理 | user-server | 未开始 | 未认领 | US-02, US-03 | `docs/03-user-server-requirements-and-tasks.md` |
| AS-01 管理服务基础与管理员认证 | admin-server | 完成 | Codex2 | 无 | `docs/04-admin-server-requirements-and-tasks.md` |
| AS-02 用户管理、积分调整、审计 | admin-server | 未开始 | 未认领 | AS-01, US-02 | `docs/04-admin-server-requirements-and-tasks.md` |
| AS-03 充值档位、模型、价格配置 | admin-server | 未开始 | 未认领 | AS-01 | `docs/04-admin-server-requirements-and-tasks.md` |
| AS-04 模型测试、任务管理、退款重试 | admin-server | 未开始 | 未认领 | AS-02, AS-03, US-04 | `docs/04-admin-server-requirements-and-tasks.md` |
| UW-01 用户端基础、登录注册、布局 | user-web | 完成 | Codex3 | 无，可先 mock | `docs/01-user-web-requirements-and-tasks.md` |
| UW-02 创作工作台、模型选择、上传提交 | user-web | 未开始 | 未认领 | UW-01, US-03 | `docs/01-user-web-requirements-and-tasks.md` |
| UW-03 结果流、继续编辑、我的作品 | user-web | 未开始 | 未认领 | UW-02, US-04 | `docs/01-user-web-requirements-and-tasks.md` |
| UW-04 充值弹窗、积分记录、体验收尾 | user-web | 未开始 | 未认领 | UW-01, US-02 | `docs/01-user-web-requirements-and-tasks.md` |
| AW-01 管理端基础、登录、控制台 | admin-web | 完成 | Codex4 | 无，可先 mock | `docs/02-admin-web-requirements-and-tasks.md` |
| AW-02 用户管理、积分流水 | admin-web | 完成 | Codex2 | AW-01, AS-02 | `docs/02-admin-web-requirements-and-tasks.md` |
| AW-03 充值档位、模型、价格配置 | admin-web | 完成 | Codex2 | AW-01, AS-03 | `docs/02-admin-web-requirements-and-tasks.md` |
| AW-04 任务管理、模型测试、审计 | admin-web | 完成 | Codex2 | AW-02, AW-03, AS-04 | `docs/02-admin-web-requirements-and-tasks.md` |
| IMG-01 图片规范、模型规格、价格矩阵、用户端报价联动 | admin-server/admin-web/user-server/user-web | 进行中 | Codex4 | AS-03, US-03, UW-02 | 本文件 |

## 任务包细化

### US-01 服务基础与认证

目标：建立 `user-server` 可运行骨架和用户登录闭环。

范围：

- FastAPI 项目结构、配置、日志、统一响应、异常处理。
- PostgreSQL async SQLAlchemy、Alembic、Redis 连接。
- `users` 表 migration。
- 密码哈希、RSA 公钥、JWT、注册、登录、`/auth/me`。
- `get_current_user` 依赖和登录限流。

交付：

- `user-server/README.md`
- `user-server/.env.example`
- `user-server/app/**`
- `user-server/alembic/**`
- 认证相关测试。

验收：

- 能启动服务。
- 能注册、登录、获取当前用户。
- 禁用用户和过期 token 返回正确错误。

### US-02 积分账户与充值订单

目标：建立积分账本和充值订单闭环。

范围：

- `user_credit_accounts`、`credit_ledger`、`recharge_orders` migration。
- 注册用户自动创建积分账户。
- 余额查询、流水查询。
- 幂等积分服务：加积分、扣积分、退款。
- 充值档位读取、订单创建。
- mock 支付 provider、支付回调、到账。

交付：

- 积分 service。
- 充值 order service。
- 并发扣积分测试。
- 支付回调幂等测试。

验收：

- 并发扣费不出现负数。
- 每次余额变化都有流水。
- 同一支付回调不会重复到账。

### US-03 模型读取、报价、上传资产

目标：用户端能读取后台发布模型，并完成图片上传和报价。

范围：

- 读取 `image_models`、`image_model_options`、`image_model_prices`。
- 用户端模型列表、模型选项、报价接口。
- Redis 模型配置缓存和版本失效。
- 图片上传、图片校验、StorageProvider 抽象。
- `image_assets` migration。

交付：

- 模型读取 API。
- 报价 API。
- 上传 API。
- 上传和报价测试。

验收：

- 停用模型不返回。
- 无 active 价格不能报价。
- 非图片/超大图片被拒绝。

### US-04 图片任务执行与作品管理

目标：完成从创建任务、扣积分、执行、保存结果到作品管理的闭环。

范围：

- `image_tasks`、`works` migration。
- 任务创建时事务内扣积分。
- 模型调用客户端抽象，第一版可 mock。
- 异步任务执行、状态查询。
- 成功保存输出资产和作品。
- 失败退款或进入人工处理。
- 作品列表、详情、采集、推荐、删除、批量导出。

交付：

- 图片任务 service。
- 作品 service。
- mock 模型执行器。
- 任务成功/失败/退款测试。

验收：

- 成功任务能生成作品。
- 失败任务积分处理正确。
- 用户不能访问他人任务和作品。

### AS-01 管理服务基础与管理员认证

目标：建立 `admin-server` 可运行骨架和后台登录闭环。

范围：

- FastAPI 项目结构、配置、日志、统一响应、异常处理。
- PostgreSQL async SQLAlchemy、Alembic、Redis 连接。
- `admin_users` migration。
- 管理员 RSA 登录、JWT、`/admin/auth/me`。
- 角色权限依赖。
- 超级管理员 seed 脚本。

交付：

- `admin-server/README.md`
- `admin-server/.env.example`
- `admin-server/app/**`
- 管理员认证测试。

验收：

- 超级管理员可登录。
- 禁用管理员不能登录。
- 无权限返回 403。

### AS-02 用户管理、积分调整、审计

目标：后台能管理用户、人工调整积分，并记录审计。

范围：

- `admin_audit_logs` migration。
- 用户列表、详情、启用/禁用、重置密码。
- 人工增加/扣减积分，复用 `credit_ledger`。
- 积分流水查询、异常标记。
- 所有写操作记录审计。

交付：

- 用户管理 API。
- 积分调整 API。
- 审计日志 API。
- 审计和积分调整测试。

验收：

- 人工扣减不能扣成负数。
- 人工调整必须填写原因。
- 写操作有 before/after 审计快照。

### AS-03 充值档位、模型、价格配置

目标：后台能配置用户端展示的充值档位、模型和积分消耗。

范围：

- `recharge_plans` migration 和 CRUD。
- `image_model_providers`、`image_models`、`image_model_options`、`image_model_prices` migration。
- provider API key 加密存储、脱敏返回。
- 模型 CRUD、上下架、排序。
- 模型选项 CRUD。
- 价格版本新增、停用旧 active 价格。
- 配置变更后刷新 Redis 配置版本。

交付：

- 充值档位 API。
- 模型配置 API。
- 价格配置 API。
- 密钥脱敏和价格版本测试。

验收：

- 历史价格不被覆盖。
- 停用模型后用户端不能再创建新任务。
- API key 不明文返回。

### AS-04 模型测试、任务管理、退款重试

目标：后台能测试模型，查看任务，处理失败任务。

范围：

- `model_test_runs` migration。
- 模型连通性测试接口。
- 测试记录查询。
- 图片任务列表、详情。
- 人工退款、失败任务重试。
- 退款和重试写审计。

交付：

- 模型测试 API。
- 任务管理 API。
- 退款/重试 API。
- 模型测试和退款幂等测试。

验收：

- base URL/API key 错误能返回可读错误。
- 同一任务不能重复退款。
- 重试不覆盖原任务历史。

### IMG-01 图片规范、模型规格、价格矩阵、用户端报价联动

目标：建立图片分辨率/尺寸比例规范主数据，并贯通模型支持规格、价格矩阵、启用校验和用户端创作页报价。

范围：

- 新增图片规范管理后台页面，包含“分辨率管理”和“尺寸管理”两个 tab。
- 新增规格主数据表：分辨率如 `1k`、`2k`、`4k`、`720p`；尺寸比例如 `1:1`、`16:9`、`9:16`。
- 模型管理新增“支持的分辨率”和“支持的尺寸”多选，新模型默认停用。
- 启用模型前校验：该模型每个二级能力、每个支持分辨率、每个支持尺寸、默认输出张数的价格组合必须存在 active 价格；否则返回缺失组合列表。
- 价格配置只能选择模型已支持的分辨率/尺寸，并继续保留历史价格版本。
- 用户端 `/create/edit` 和 `/create/text-to-image` 只展示已启用且支持对应能力的模型。
- 用户端选择模型后，分辨率/尺寸从当前模型支持项读取；报价接口按模型、能力、分辨率、尺寸、输出张数返回真实积分消耗。

任务拆分：

- IMG-01A：admin-server 新增图片规范、模型规格关联、启用校验、价格校验 API。
- IMG-01B：admin-web 新增图片规范管理页，改造模型表单和价格配置表单。
- IMG-01C：user-server 接通真实模型列表和报价接口，禁止停用/不支持能力/无价格组合。
- IMG-01D：user-web 创作与编辑页按模型能力、规格和报价联动展示。

验收：

- 无规范或无价格组合的模型不能启用，并能返回缺失组合。
- 用户端不能选择停用模型、不能选择模型不支持的分辨率/尺寸。
- 用户端展示的消耗积分来自真实报价接口，不是前端固定值。

### UW-01 用户端基础、登录注册、布局

目标：建立 `user-web` 可运行骨架和登录后主布局。

范围：

- React + TypeScript + Vite 项目结构。
- 请求客户端、401 处理、auth store、路由守卫。
- 登录页、注册页、RSA 密码加密。
- 主布局：左侧导航、顶部栏、账号菜单、积分展示占位、主题切换。
- mock API client，真实接口未完成前可用 mock。

交付：

- `user-web/README.md`
- `user-web/.env.example`
- 登录注册页面。
- 主布局组件。

验收：

- 本地可启动。
- 未登录跳登录。
- 登录后进入创作工作台布局。

### UW-02 创作工作台、模型选择、上传提交

目标：完成图片 AI 编辑核心表单。

范围：

- 模型列表和模型卡片。
- 图片上传组件。
- 提示词输入。
- 分辨率和尺寸比例选择。
- 价格预估展示。
- 提交任务和轮询状态。
- 余额不足引导充值。

交付：

- 图片 AI 编辑页面。
- 模型/上传/报价/任务 service。
- 表单状态和错误状态。

验收：

- 模型和价格来自接口或 mock service。
- 余额不足不能提交。
- 提交后出现处理中状态。

### UW-03 结果流、继续编辑、我的作品

目标：完成结果展示和作品管理主体验。

范围：

- 右侧作品流。
- 原图/结果图对比。
- 预览、下载、采集、推荐、删除。
- 更多编辑菜单入口。
- 继续编辑区域。
- 我的作品页面：tab、分类、状态筛选、搜索、分页、批量操作。

交付：

- 结果卡片组件。
- 我的作品页面。
- 作品 service。

验收：

- 删除有确认。
- 操作有 loading 和反馈。
- 列表分页加载，空状态完整。

### UW-04 充值弹窗、积分记录、体验收尾

目标：完成积分购买和用户端体验闭环。

范围：

- 充值弹窗、档位选择、创建订单。
- 支付二维码或 mock 支付状态。
- 订单状态轮询。
- 积分记录页。
- 响应式和体验收尾。

交付：

- 充值组件。
- 积分记录页面。
- 充值和积分 service。

验收：

- 重复点击不会创建多个订单。
- 支付成功后刷新余额。
- 积分流水筛选可用。

### AW-01 管理端基础、登录、控制台

目标：建立 `admin-web` 可运行骨架和后台基础布局。

范围：

- React + TypeScript + Vite 项目结构。
- 请求客户端、auth store、路由守卫、权限 hook。
- 管理员登录页。
- 后台布局、侧边菜单、顶部用户区。
- 控制台指标和最近记录。
- mock API client，真实接口未完成前可用 mock。

交付：

- `admin-web/README.md`
- `admin-web/.env.example`
- 登录和控制台页面。

验收：

- 本地可启动。
- 未登录跳登录。
- 无权限菜单不展示或禁用。

### AW-02 用户管理、积分流水

目标：完成后台用户和积分管理页面。

范围：

- 用户列表、搜索、筛选、分页。
- 用户详情抽屉。
- 启用/禁用、重置密码。
- 人工加减积分表单。
- 积分流水列表、筛选、异常标记。

交付：

- 用户管理页面。
- 积分流水页面。
- 用户和积分 service。

验收：

- 人工调整必须填写原因。
- 危险操作有确认。
- 列表服务端分页。

### AW-03 充值档位、模型、价格配置

目标：完成后台核心配置页面。

范围：

- 充值档位列表、新增/编辑、上下架、排序。
- 模型 provider 列表和编辑。
- 模型列表和编辑。
- 模型选项配置。
- 模型价格版本配置。
- API key 脱敏展示。

交付：

- 充值档位页面。
- 模型管理页面。
- 价格配置页面。

验收：

- API key 不回显明文。
- 价格变更必须填写原因。
- 下架配置前端不再展示。

### AW-04 任务管理、模型测试、审计

目标：完成后台任务处理和审计页面。

范围：

- 模型测试表单和结果展示。
- 模型测试记录。
- 图片任务列表、筛选、详情。
- 人工退款、失败重试。
- 审计日志列表。

交付：

- 模型测试 UI。
- 任务管理页面。
- 审计日志页面。

验收：

- 退款/重试有确认和原因。
- 测试失败展示错误摘要。
- 审计日志可按操作者和时间筛选。

## 认领记录模板

每个 Codex 完成认领后，在下面追加一行。

| 时间 | Codex | 认领任务包 | 备注 |
| --- | --- | --- | --- |
| 2026-06-19 | Codex3 | UW-01 用户端基础、登录注册、布局 | 按四 Codex 并行策略负责 user-web，先基于 mock API 开发基础骨架 |
| 2026-06-19 14:56 CST | Codex1 | US-01 服务基础与认证 | 创建 user-server 基础骨架、认证、users migration 与测试 |
| 2026-06-19 | Codex4 | AW-01 管理端基础、登录、控制台 | 创建 `admin-web/`，完成登录、路由守卫、权限菜单和控制台。 |
| 2026-06-19 14:55 | Codex2 | AS-01 管理服务基础与管理员认证 | 创建 `admin-server/`，实现 FastAPI 基础、管理员认证、权限依赖、seed 和测试 |
| 2026-06-19 15:08 | Codex2 | AW-02 用户管理、积分流水 | 补齐管理端用户管理和积分流水页面，接入真实管理端 API，接口无数据时显示空状态 |
| 2026-06-19 15:18 | Codex2 | AW-03 充值档位、模型、价格配置 | 补齐充值档位、模型管理、模型测试、价格版本配置页面 |
| 2026-06-19 15:18 | Codex2 | AW-04 任务管理、模型测试、审计 | 补齐任务退款/重试、审计日志查询页面 |

## 完成记录模板

每个 Codex 完成任务后，在下面追加一行。

| 时间 | Codex | 完成任务包 | 主要交付 | 验证命令 |
| --- | --- | --- | --- | --- |
| 2026-06-19 | Codex3 | UW-01 用户端基础、登录注册、布局 | `user-web/README.md`、`.env.example`、Vite React 骨架、auth store、请求客户端、登录注册页、主布局、mock API | `npm run build`; `npm run lint`; `npm run dev` |
| 2026-06-19 15:02 | Codex2 | AS-01 管理服务基础与管理员认证 | `admin-server/` FastAPI 骨架、统一响应/异常/配置/日志、async SQLAlchemy/Alembic、Redis client、`admin_users` migration、RSA 公钥/登录、JWT、当前管理员与角色依赖、超级管理员 seed、认证安全测试 | `python3 -m compileall admin-server/app admin-server/scripts admin-server/tests`; `PYTHONPATH=admin-server python3 - <<'PY' ... healthz/security smoke ... PY`; `cd admin-server && PYTHONPATH=. alembic heads` |
| 2026-06-19 | Codex4 | AW-01 管理端基础、登录、控制台 | `admin-web/README.md`、`.env.example`、React/Vite 项目骨架、登录页、路由守卫、权限菜单、后台布局、控制台页面 | `cd admin-web && npm run build` |
| 2026-06-19 15:02 CST | Codex1 | US-01 服务基础与认证 | `user-server/README.md`、`.env.example`、FastAPI 应用、users migration、认证路由、认证测试 | `python3 -m pytest`; `alembic upgrade head` |
| 2026-06-19 15:18 | Codex2 | AW-02 用户管理、积分流水 | `admin-web/src/pages/ManagementPages.tsx` 用户列表、搜索、详情侧栏、启禁用确认、人工调分弹窗、积分流水查询、异常标记弹窗；`admin-web/src/services/adminApi.ts` 真实接口调用；删除本地业务演示数据 | `cd admin-web && npm run build` |
| 2026-06-19 15:18 | Codex2 | AW-03 充值档位、模型、价格配置 | 充值档位增改/上下架、模型列表/上下架/连通性测试、价格版本新增/停用，API key 脱敏展示，价格变更原因校验 | `cd admin-web && npm run build` |
| 2026-06-19 15:18 | Codex2 | AW-04 任务管理、模型测试、审计 | 任务列表、失败任务退款原因、失败任务重试确认、审计日志搜索；统一产品弹窗替代浏览器确认 | `cd admin-web && npm run build` |
