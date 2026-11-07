# Docker Compose 一键部署说明

## 服务

`docker-compose.yml` 会启动：

- `postgres`：PostgreSQL 16
- `redis`：Redis 7
- `user-server`：用户端 FastAPI，宿主机默认 `http://localhost:8000`
- `admin-server`：管理端 FastAPI，宿主机默认 `http://localhost:8001`
- `user-web`：用户端 Web，宿主机默认 `http://localhost:3000`
- `admin-web`：管理端 Web，宿主机默认 `http://localhost:3001`

## 启动

```bash
cp .env.docker.example .env
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f user-server admin-server
```

只重启前端容器，不重新构建镜像：

```bash
docker compose up -d user-web admin-web
```

用户端 Web 默认仅绑定 `127.0.0.1`。需要通过公网 IP 加端口访问时，在 `.env` 设置
`USER_WEB_BIND_ADDRESS=0.0.0.0` 和所需的 `USER_WEB_PORT`（例如 `3002`），然后执行：

```bash
docker compose up -d --no-deps --no-build user-web
```

此时可访问 `http://服务器IP:3002/login`。该入口使用 HTTP，日常登录优先使用 HTTPS 域名。
恢复仅本机访问时，将 `USER_WEB_BIND_ADDRESS` 改为 `127.0.0.1` 后执行同一命令。

停止：

```bash
docker compose down
```

清空数据库和 Redis 数据：

```bash
docker compose down -v
```

## 默认账号

管理端 seed 脚本会创建超级管理员：

- 用户名：`.env` 的 `SUPER_ADMIN_USERNAME`，默认 `admin`
- 密码：`.env` 的 `SUPER_ADMIN_PASSWORD`，默认 `ChangeMe123!`

## OpenAgent 七牛发包配置

OpenAgent 后台发布页不走 MinIO。管理员选择本地安装包后，管理端接口
`/admin/openagent/upload-token` 会读取 `.env` 里的七牛配置生成上传凭证，浏览器直传七牛，
后台只保存最终公开下载地址。

```env
QINIU_ACCESS_KEY=
QINIU_SECRET_KEY=
QINIU_BUCKET=
QINIU_CDN_BASE_URL=
QINIU_UPLOAD_HOST=https://upload.qiniup.com
OPENAGENT_RELEASE_PREFIX=openagent/releases
```

- `QINIU_BUCKET`：OpenAgent 安装包所在七牛空间。
- `QINIU_CDN_BASE_URL`：用户下载访问的 CDN 域名，例如 `https://download.example.com`。
- `QINIU_UPLOAD_HOST`：七牛上传域名，华东默认可用 `https://upload.qiniup.com`，其他区域按七牛空间配置调整。
- `OPENAGENT_RELEASE_PREFIX`：包文件在七牛空间内的目录前缀。

## 七牛图片存储

默认图片存储为 MinIO。设置以下配置后，新上传图片和新生成图片会写入七牛云；数据库中的历史 MinIO URL 保持不变，读取时继续使用原地址，无需迁移。

```env
USER_UPLOAD_STORAGE_PROVIDER=qiniu
USER_QINIU_IMAGE_PREFIX=image2-assets
```

图片存储复用 `QINIU_ACCESS_KEY`、`QINIU_SECRET_KEY`、`QINIU_BUCKET`、`QINIU_CDN_BASE_URL` 与 `QINIU_UPLOAD_HOST`。也支持用同名的 `USER_QINIU_*` 配置覆盖。请确保 `QINIU_CDN_BASE_URL` 是已绑定 CDN 的公开访问域名。

需要同时使用多个对象存储或 CDN 厂商时，使用命名目标配置。`USER_IMAGE_STORAGE_TARGET` 仅影响后续写入；每个图片资产会保存完整 URL，故旧 MinIO、旧 CDN 和不同目标的新 CDN 可以长期并存读取。

```env
USER_IMAGE_STORAGE_TARGET=qiniu-primary
USER_IMAGE_STORAGE_TARGETS_JSON={"qiniu-primary":{"provider":"qiniu","bucket":"image-primary","cdn_base_url":"https://img-primary.example.com","key_prefix":"image2-assets","access_key":"...","secret_key":"...","upload_host":"https://upload.qiniup.com"},"qiniu-secondary":{"provider":"qiniu","bucket":"image-secondary","cdn_base_url":"https://img-secondary.example.com","key_prefix":"image2-assets","access_key":"...","secret_key":"...","upload_host":"https://upload.qiniup.com"}}
```

当前实现支持 `minio` 与 `qiniu` 两种写入提供方；接入其他对象存储时新增对应提供方实现即可，不会影响已保存 URL 的读取。

## Cloudflare R2 图片加速（可选）

R2 在这里作为三天热层，不替代服务器上的 MinIO 备份。开启后，用户浏览器
通过预签名 PUT 直传 R2，user-server 只负责校验并从 R2 写入一份 MinIO 备份；
生成结果如果上游已经返回 R2 链接，也只保存本地备份，不会再次上传 R2。接口返回
R2 热链，超过 `USER_R2_HOT_URL_TTL_SECONDS` 后自动返回 `local_url`。

```env
USER_R2_ENABLED=true
USER_R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
USER_R2_ACCESS_KEY_ID=<r2-access-key-id>
USER_R2_SECRET_ACCESS_KEY=<r2-secret-access-key>
USER_R2_BUCKET=<bucket-name>
USER_R2_PUBLIC_BASE_URL=https://<public-r2-domain>
USER_R2_UPLOAD_EXPIRES_SECONDS=900
USER_R2_HOT_URL_TTL_SECONDS=259200
```

R2 存储桶还需要配置 CORS，允许用户站点对 `PUT`、`GET`、`HEAD` 发起跨域请求，
并允许 `Content-Type` 请求头；否则前端会自动回退到原来的 multipart 上传。请同时
配置 R2 生命周期规则清理 `image2-staging/` 前缀，保留时间至少覆盖热链有效期。

## 初始化数据

后端容器启动时会自动执行 Alembic migration 创建表结构。确认服务健康后，可以按需要导入根目录的数据脚本：

```bash
docker compose ps
```

只导入后台账号、模型、价格、充值档位、签到/邀请配置等初始化/配置数据：

```bash
docker exec -i image2-postgres psql -U image2 -d image2 -v ON_ERROR_STOP=1 < initial_data.sql
```

完整复现当前开发库全部数据，包括用户、积分流水、图片任务、图片资产、审计日志和配置数据：

```bash
docker exec -i image2-postgres psql -U image2 -d image2 -v ON_ERROR_STOP=1 < all_data.sql
```

如果 SQL 数据里的图片地址来自其他 MinIO 地址，导入后执行 URL 同步脚本。脚本读取 `.env` 中的 `USER_DATABASE_URL`、`USER_MINIO_PUBLIC_ENDPOINT`、`USER_MINIO_BUCKET`，按 `image_assets.storage_key` 修正 `image_assets` 和 `image_tasks` 中的图片地址：

```bash
python3 scripts/sync_minio_urls.py
```

两份 SQL 都使用 `INSERT ... ON CONFLICT DO NOTHING`，可重复执行。`all_data.sql` 包含用户数据和模型供应商密钥字段，只能在有权限的开发环境内使用。

## 前端 API 模式

当前前端只请求真实接口，不再内置管理端或用户端业务演示数据。

如果接口尚未实现，页面会显示空状态或接口错误。重新构建前端：

```bash
docker compose up -d --build user-web admin-web
```

注意：`--build` 会重新解析 `node:22-alpine` 和 `nginx:1.27-alpine` 等基础镜像。即使本地已有业务镜像，Docker 也可能访问 Docker Hub 校验元数据；如果网络被重置，会出现 `failed to fetch anonymous token`。没有修改前端源码或 Vite 构建变量时，不要加 `--build`，直接执行：

```bash
docker compose up -d user-web admin-web
```

## 反向代理路径

- 用户端 Web 请求 `/api/**`，Nginx 反代到 `user-server:8000/**`。
- 管理端 Web 请求 `/admin-api/**`，Nginx 反代到 `admin-server:8000/**`。
- 团队控制台使用 `https://team.shyfai.com/<site_key>/`；其内部 Nginx 将 `/<site_key>/api/**` 反代到 `user-server:8000/**`，并受控传递子站标识。公网 Nginx 配置见 `deploy/nginx/image2-shyfai.com.conf`，容器内部端口默认为 `127.0.0.1:3003`。

这样浏览器访问前端时不会遇到跨域问题。

## Alembic 迁移

两个后端共享同一个数据库，但使用独立 Alembic version table：

- `user_server_alembic_version`
- `admin_server_alembic_version`

容器启动命令会先执行 `alembic upgrade head`，再启动 Uvicorn。
