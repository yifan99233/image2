# 图片 AI 编辑平台总体需求与架构

## 目标

建设一套面向用户的图片 AI 编辑平台，支持注册登录、积分充值、积分消费、图片模型切换、图片生成/编辑、作品管理，并配套独立管理后台，用于用户、积分、充值档位、模型、模型消耗积分、模型连通性测试等运营配置。

系统按四个独立项目交付和部署：

- `user-web`：用户端 React Web。
- `admin-web`：管理端 React Web。
- `user-server`：用户端 FastAPI 服务，承载注册登录、用户资产、图片任务、作品等用户业务接口。
- `admin-server`：管理端 FastAPI 服务，承载后台账号、用户管理、积分管理、充值档位、模型配置、价格配置、审计等管理接口。

技术栈约束：

- 前端：React。
- 服务端：FastAPI。
- 数据库：PostgreSQL。
- 缓存/限流/任务状态：Redis。
- 登录注册、密码加密、JWT 鉴权参考 `/Users/apple/work/testflow3.0`。

## 参考项目结论

参考项目关键实现位置：

- 后端认证路由：`/Users/apple/work/testflow3.0/Server/app/api/endpoints/auth.py`
- 后端 JWT/密码：`/Users/apple/work/testflow3.0/Server/app/services/security.py`
- 后端当前用户依赖和 Redis 权限缓存：`/Users/apple/work/testflow3.0/Server/app/api/deps.py`
- 前端请求拦截和 401 处理：`/Users/apple/work/testflow3.0/web/src/services/http.ts`
- 前端认证状态：`/Users/apple/work/testflow3.0/web/src/store/authStore.ts`
- 前端登录 RSA 加密密码：`/Users/apple/work/testflow3.0/web/src/services/auth.ts`

本项目必须复用这些成熟思路，但不要复制无关的企业/项目/RBAC 复杂度：

- 密码哈希使用 PBKDF2-SHA256 或 Argon2/bcrypt，必须加盐、常量时间比较。
- JWT 使用 `sub`、`username`、`iat`、`exp`，过期时间通过环境变量配置。
- 登录接口支持前端 RSA 公钥加密密码，后端私钥解密；本地开发可允许明文降级，生产环境必须关闭明文降级。
- 请求统一返回结构，前端统一处理 401、错误提示、token 注入。
- Redis 用于验证码/登录限流/权限或配置缓存/任务状态短缓存，不作为账本真实来源。

## 产品模块

用户端模块：

- 账号：注册、登录、退出、账号设置、个人资料、密码修改。
- 积分：当前余额展示、充值、充值记录、消费记录。
- 图片 AI 创作：图片 AI 编辑、图像 AI 生成、批量生图、批量改图、商品主图类工具。
- 模型切换：按场景展示模型，支持模型标签、推荐、稳定、新模型、速度提示、支持分辨率/尺寸。
- 图片上传：单图/多图上传，格式和大小校验，上传进度，失败重试。
- 图片任务：选择模型、输入提示词、选择分辨率、尺寸比例，提交任务，扣积分，轮询任务状态，展示结果图。
- 继续编辑：基于结果图再次输入指令生成新任务。
- 作品管理：我的作品、我的采集、分类、搜索、筛选、预览、下载、推荐、采集、删除、批量导出。
- 运营入口：签到得积分、邀请赚积分、客服、会员/授权、API 接入入口可先预留。

管理端模块：

- 管理员登录和权限控制。
- 用户管理：查询、禁用/启用、详情、充值/扣减积分、查看积分流水。
- 积分管理：人工调整、流水审计、异常账务核查。
- 充值档位配置：金额、赠送积分、排序、上下架、推荐标签。
- 模型管理：模型名称、供应商、base URL、API key、模型标识、能力、状态、优先级、超时、重试、并发限制。
- 模型连通性测试：保存前/保存后测试，记录请求耗时、响应摘要、错误原因。
- 模型消耗积分配置：按模型、能力、分辨率、尺寸、批量数量配置消耗积分。
- 创作记录管理：查看任务、状态、用户、模型、积分消耗、失败原因，可补偿积分。
- 系统配置和审计：管理员操作日志、敏感配置加密、配置版本。

## UI 参考

根目录截图显示竞品的用户端形态：

- 左侧固定导航，按 `AI创作`、`商品主图` 等分组。
- 顶部工具条展示 API 接入、客服、签到、邀请、授权、积分余额、账号菜单。
- 主工作区左侧为分步骤表单：选择模型、上传图片、文字描述、分辨率、尺寸比例、生成按钮。
- 主工作区右侧为作品结果流：原图/结果图对比、采集、推荐、下载、更多编辑、删除、继续编辑。
- 我的作品页支持深色/浅色主题、分类侧栏、状态筛选、搜索、批量采集、卡片网格。
- 充值弹窗展示当前积分、充值档位、支付二维码、到账提示。

本项目用户端可以参考布局和交互节奏，但品牌、文案、配色、资产必须独立设计，不能直接复刻竞品商标或完整视觉素材。

## 核心数据一致性要求

- 积分余额不能只存前端或 Redis；PostgreSQL 为唯一真实来源。
- 所有积分变更必须写入 `credit_ledger` 流水，包含幂等键、业务类型、变更前后余额、操作者、关联订单/任务。
- 图片任务创建和扣积分必须在数据库事务中完成；外部模型调用失败后按策略自动退还或进入人工处理。
- 同一支付回调、同一任务重试、同一后台人工操作必须通过 `idempotency_key` 防重。
- 模型价格配置变更只影响新任务，历史任务必须保存当时的模型、分辨率、积分单价快照。
- API key、支付密钥、模型密钥必须加密存储，接口返回只展示脱敏值。

## 并行开发边界

四个 Codex 并行时按以下边界工作：

- `user-web` 只依赖用户端 OpenAPI，不直接访问管理端接口。
- `admin-web` 只依赖管理端 OpenAPI，不直接访问用户端接口。
- `user-server` 只提供用户业务接口，读取已启用的模型/价格配置，不提供配置写接口。
- `admin-server` 负责配置、用户、积分、审计写操作，可查询用户任务和流水。
- 两个服务端共享 PostgreSQL 数据库和 Redis，但不要共享运行时代码目录；共享契约通过文档和 migration 命名约定协调。

## 建议目录

```text
image2/
  docs/
  user-web/
  admin-web/
  user-server/
  admin-server/
```

每个项目都需要独立的 README、环境变量示例、启动脚本、测试脚本和部署说明。

## 本地初始化数据

项目根目录保留两份数据库数据脚本，供新开发环境初始化使用：

- `initial_data.sql`：只包含后台账号、模型、价格、充值档位、签到/邀请配置等初始化/配置数据。
- `all_data.sql`：包含当前开发库所有表的数据，包括用户、积分流水、图片任务、图片资产、审计日志和配置数据。

推荐新开发只需要基础配置时使用 `initial_data.sql`；需要完整复现当前开发库状态时使用 `all_data.sql`。

使用流程：

```bash
cp .env.docker.example .env
docker compose up -d --build
docker compose ps
```

等待 `postgres`、`redis`、`user-server`、`admin-server` 都变为 healthy 后，导入数据：

```bash
# 只导入初始化/配置数据
docker exec -i image2-postgres psql -U image2 -d image2 -v ON_ERROR_STOP=1 < initial_data.sql

# 或完整导入当前开发库全部数据
docker exec -i image2-postgres psql -U image2 -d image2 -v ON_ERROR_STOP=1 < all_data.sql
```

如果导入的数据来自其他 MinIO 地址，导入后执行 URL 同步脚本。脚本会读取 `.env` 中的 `USER_DATABASE_URL`、`USER_MINIO_PUBLIC_ENDPOINT`、`USER_MINIO_BUCKET`，按 `image_assets.storage_key` 修正 `image_assets` 和 `image_tasks` 里的图片地址：

```bash
python3 scripts/sync_minio_urls.py
```

两份 SQL 都是 `INSERT ... ON CONFLICT DO NOTHING` 格式，可重复执行。导入前必须先让容器启动完成，因为后端容器启动时会自动执行 Alembic migration 创建表结构。

注意：`all_data.sql` 是完整开发数据快照，会包含用户数据、任务记录、积分流水、审计日志，以及模型供应商表中的密钥字段；不要提交到公开仓库或发给无权限人员。
