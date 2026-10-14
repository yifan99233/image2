# 造梦引擎 Admin Web

管理端 React Web。页面只请求真实 `admin-server` 接口，不内置本地业务演示数据。

## 启动

```bash
npm install
npm run dev
```

默认端口：`http://localhost:5174`

## 验证

```bash
npm run build
```

## 环境变量

复制 `.env.example` 为 `.env.local` 后可调整：

- `VITE_ADMIN_API_BASE_URL`：管理端 API 地址。
- `VITE_SITE_FRONTEND_ROOT_DOMAIN` / `VITE_SITE_ADMIN_ROOT_DOMAIN`：用户端和管理端站点根域名。
- `VITE_SITE_FRONTEND_BASE_SUBDOMAIN` / `VITE_SITE_ADMIN_BASE_SUBDOMAIN`：子站域名前缀。
- `VITE_SITE_FRONTEND_URL`：主用户站公开地址，同时用于支付回调默认值。
