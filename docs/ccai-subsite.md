# CCAI 子站

- 前台：`https://ccai.fycsai.com`
- 后台：`https://admin.ccai.fycsai.com`
- 请求路径：DNS → V4 (`180.178.56.82`) HTTPS edge → V3 (`38.147.104.202`) image2 共享服务。保留 CCAI Host，站点数据由独立 site_id 隔离。
- V4 配置位于 `ops/magic-v4-edge-20261008` 分支的 `deploy/magic-v4-edge/sites/ccai.conf`，证书 `ccai.fycsai.com`，续期脚本 `install-ccai-certificate.sh`。
- V3 配置为 `deploy/nginx/image2-ccai-v3.conf`；V4 回源 TLS SNI 使用已有 `magic.shyfai.cn`，校验证书，不关闭验证。
- 创建时复制基础配置、模型及其规格与价格、充值档位及支付设置；回调地址替换为 CCAI 域名。不复制客户、订单、账本、任务或登录凭证。
- Agent 对接及启用模型只允许 agent5；复制时移除其他上游的旧凭证并停用其渠道，保留停用模型及历史价格供管理查阅。

## 部署

通过 Git 推送和服务器 `git pull --ff-only` 获取对应配置。V3 将配置软链到 `/etc/nginx/sites-enabled/image2-ccai-v3`，执行 `nginx -t` 后 reload；不需要重建或重启共享业务容器。

V4 使用现有 `/opt/magic-v4-edge` Compose，安装 CCAI 证书和专属续期 hook，构建新 edge 镜像，先用 `docker compose run --rm --no-deps edge -t` 校验，再切换。只新增 CCAI DNS A 记录，保留现有泛域名、邮件和其他站点记录。

## 校验与恢复

上线校验两个 Host 返回独立 site_key，模型列表和充值档位与模板一致，回调域名正确，无 agent3 上游；管理员登录按站点权限限制。GET agent5 分组和模型仅用于只读连通检查；未进行真实充值和收费生图。

数据库配置创建在一个事务中完成，并在事务前备份数据库。失败回滚，不留下半建站点。上线后若需撤回，先停用 CCAI 站点并移除其入口；如已有用户或订单，保留数据，不能用整库恢复影响其他站点。

## 2026-10-12 开通记录

- 站点 ID `10`，站点标识 `ccai`，展示名 `CCAI`。
- 配置来源为 `magic.shagentai.com` 的 `main` 站点快照；复用 V3 总站已有模型及支付凭证，凭证未导出到快照。
- 共 20 个模型（7 个启用）、816 条价格版本（495 条当前有效）、13 个充值档位（3 个启用）。有效档位为 19.9 试用、68.80 基础充值、199 团队版；价格和档位逐条比对通过。
- Agent 对接复用 V3 `mzart` 子站的 agent5 配置：文本组 2，图片组 15，兑换系数 100。4 种启用模型的 `/v1/models` 鉴权和模型可见性检查通过。
- 14 个旧渠道保持停用，并清空非 agent5 的地址和凭证。未创建或复制终端客户，现有系统超级管理员可登录后台。
- 备份：V3 `/data/backups/image2/pre-ccai-20261012.dump`（54 MB）。初始化记录在管理员审计日志中。
- V4 配置提交 `7d90d06`。V3 共享业务容器保持原镜像，本次只新增站点配置和 Nginx 入口，未执行 VIP／小数积分迁移。
- 公网 HTTPS、双端站点识别、鉴权后的后台模型／价格／充值／Agent／支付回调读取均通过。未执行真实充值、账户同步注册或收费生图。
