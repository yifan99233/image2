# 发布维护页

维护页使用服务器上的运行时标记控制，不需要登录，也不会依赖前端接口。先把 `deploy/nginx/image2-maintenance.inc` include 到 V2 的三个 HTTPS server block（用户端、管理端、团队端），然后执行发布流程：

```bash
cd /mnt/work/image2
./scripts/maintenance-mode.sh on
trap './scripts/maintenance-mode.sh off' EXIT
git pull --ff-only
docker compose up -d --build user-web
curl -fsS http://127.0.0.1:3002/ >/dev/null
./scripts/maintenance-mode.sh off
trap - EXIT
```

`on` 会把 `user-web/public/maintenance.html` 安装到 `/var/www/image2-maintenance/maintenance.html` 并创建 `/var/run/image2-maintenance.flag`；`off` 删除标记并重新加载 Nginx。发布或健康检查失败时，维护标记会保留，避免用户看到半更新状态；确认服务恢复后再执行 `./scripts/maintenance-mode.sh off`。

V1 不使用这套 V2 标记和 Nginx include，不会受到影响。
