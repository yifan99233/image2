# 画布集成

登录后的「图片创意 → 画布」入口为 `/create/canvas`。源码来自
[Infinite Canvas](https://github.com/basketikun/infinite-canvas)，固定版本见
`canvas-web/UPSTREAM.md`，MIT 许可证与署名保留在 `canvas-web/LICENSE` 和页面中。

## 结构与能力

- `canvas-web` 独立构建为 `/canvas-app/`，由本站同源 iframe 承载，避免影响主站组件样式。
- `user-web/src/pages/canvas/host.ts` 接收经过来源检查的消息，通过主站服务访问账号、模型、积分报价、生图任务、上传及素材库。画布无需填写供应商密钥。
- `user-server/app/api/routes/canvas.py` 提供画布列表、详情、保存和删除。PostgreSQL 的 `canvas_projects` 按站点、用户隔离数据，列表分页且不读取完整文档。
- 支持图片与文本节点、连线、移动缩放、分组、撤销重做、图片上传、素材插入、文生图/参考图生成及包含图片文件的 ZIP 导入导出。视频、音频、Local Agent、外部插件及供应商配置入口未启用。
- 生图继续使用已有任务队列与计费接口。任务 ID 随画布保存，重新打开时查询原任务；点击失败节点重试前也先检查已有任务状态。
- 切换主站菜单保留已打开的画布；退出账号后销毁对应实例。刷新页面后从画布库重新打开。

画布编辑延迟 400 ms 合并保存，写入按画布串行执行。`revision` 防止多个页面互相覆盖，`mutation_id` 支持保存响应丢失后的幂等重试。遇到冲突会提示导出备份再重新加载。保存失败保留当前页面中的编辑并显示重试；尚未保存时离开页面会触发浏览器提示。此版本不提供离线持久化草稿，未成功保存前强制关闭浏览器仍可能丢失修改。

云端文档仅存长期可用的图片 URL，不接受浏览器临时 Blob URL 或内嵌图片。图片文件继续由现有上传与素材服务管理。删除画布采用软删除，旧页面不能恢复已删除记录；图片资产不会随画布一起删除。画布数据随 PostgreSQL 备份，图片随现有对象/文件存储备份。

供应商返回图片 URL 时可以不包含宽高。此时先保留可见的节点区域，原图加载后读取真实尺寸并保存；已保存为 1×1 且缺少图片尺寸的旧节点会在打开画布时自动恢复，不重新提交生图任务。已有有效图片尺寸的手动缩放不会在重新打开时被重置。

从左侧列表定位节点时，选择状态与操作工具栏同步切换，并收起其他节点的编辑面板。

可选后端设置（沿用现有配置加载方式）：`CANVAS_MAX_DOCUMENT_BYTES` 默认 10 MiB，`CANVAS_MAX_NODES` 默认 10000。

## 本地构建

在仓库根目录分别执行：

```sh
npm ci --prefix canvas-web
npm ci --prefix user-web
npm run build --prefix user-web
```

主站 `prebuild` / `predev` 自动构建画布到 `user-web/public/canvas-app`，该产物不提交 Git。编辑画布源码后重新执行 `npm run build:canvas --prefix user-web`。Docker 构建上下文已改为仓库根目录：

```sh
docker build -f user-web/Dockerfile -t image2-canvas-web:test .
```

部署包含后端迁移 `20260916_0100`，必须先对目标数据库执行正常的 user-server Alembic 升级，再启用新前端。按项目既有 Git 发布流程发布；本次本地验证不代表已部署线上。

## 验证

后端测试使用独立 PostgreSQL，禁止指向生产数据库：

```sh
docker compose -p image2-canvas-test -f user-server/tests/canvas-compose.yml up -d --wait
```

全新测试库需要满足仓库现有跨服务迁移依赖，按顺序执行：

```sh
cd user-server
DATABASE_URL=postgresql+asyncpg://canvas_test:canvas_test@127.0.0.1:55439/image2_canvas_test uv run alembic upgrade 20260704_0420
cd ../admin-server
DATABASE_URL=postgresql+asyncpg://canvas_test:canvas_test@127.0.0.1:55439/image2_canvas_test uv run alembic upgrade head
cd ../user-server
DATABASE_URL=postgresql+asyncpg://canvas_test:canvas_test@127.0.0.1:55439/image2_canvas_test uv run alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://canvas_test:canvas_test@127.0.0.1:55439/image2_canvas_test uv run --extra test pytest tests/test_canvas.py -q
```

测试覆盖真实数据库读写、用户/站点隔离、保存重试、多页面竞争、分页、文档校验及删除后禁止恢复。

浏览器测试需要已构建主站和 Chrome（可用 `CANVAS_TEST_BROWSER` 设置 Playwright 浏览器 channel）。两个终端分别执行：

```sh
npm run preview --prefix user-web -- --host 127.0.0.1 --port 5179
npm run test:smoke --prefix canvas-web
```

浏览器测试使用真实 960×640 图片和受控 HTTP 响应，不调用收费模型，验证缺少宽高的图片生成、旧 1×1 节点恢复、手动尺寸保留、文本生成连线、工具栏定位、画布缩放、任务恢复不重复提交、素材插入、菜单切换、撤销重做、ZIP 导入导出及项目切换。真实供应商生成与实际扣费需在配置好模型的目标环境单独验证。

测试完可清理专用临时数据库（tmpfs 数据会销毁）：

```sh
docker compose -p image2-canvas-test -f user-server/tests/canvas-compose.yml down
```
