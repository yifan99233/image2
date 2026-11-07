# user-web

用户端图片 AI 创作平台，负责普通用户登录注册、创作工作台、积分展示和后续作品管理体验。

## 快速开始

```bash
npm install
npm run dev
```

默认请求真实用户端 API：

```bash
cp .env.example .env
```

## 环境变量

- `VITE_API_BASE_URL`：用户端服务地址。

## 当前交付

- React + TypeScript + Vite 骨架。
- 统一请求客户端和 401 会话失效处理。
- Zustand auth store。
- 登录页、注册页、受保护路由和登录后回跳。
- 登录后主布局、侧边导航、顶部栏、积分占位和主题切换。

## 验证

```bash
npm run build
npm run lint
```
