# 绘境 AI 子站

- Site key: `huijing`; display name: `绘境 AI`.
- Frontend: `https://art.hzhjai.com`; admin: `https://admin.hzhjai.com`.
- `hzhjai.com` and `www.hzhjai.com` redirect to `art.hzhjai.com`.
- Registrar: Spaceship; authoritative DNS: Cloudflare.
- DNS-only A records for `@`, `www`, `art`, and `admin` point to V3 `38.147.104.202`.
- Uses the running shared image2 containers, with independent tenant users,
  orders, tasks, and balances. Template is the production main site (ID 1).

## Provisioning

1. Commit and push these files, then pull them in `/data/workspace/image2`.
2. Back up the configuration tables to a private file before creating configuration.
3. Dry-run `docker exec -i image2-admin-server python < scripts/provision-huijing.py`.
   The script invokes the deployed, audited site-creation handler when passed
   `--apply`; it copies model, price, recharge, Agent and payment configuration
   through the existing transaction, with the target payment callback URLs.
   It does not copy customers or create an additional administrator.
4. Enable `image2-huijing.bootstrap.conf` through the new symlink
   `/etc/nginx/sites-enabled/image2-huijing`; run `nginx -t`, then reload.
5. After DNS delegation and A records resolve, run Certbot HTTP-01 with webroot
   `/var/www/html`, certificate name `hzhjai.com`, and all four hostnames.
   Install a renewal deploy hook `nginx -t && systemctl reload nginx`.
6. Point the same symlink to `image2-huijing-v3.conf`; validate and reload.

No shared application image is replaced and no existing site's configuration
is changed. Both new application virtual hosts include the existing Magic
maintenance switch for future releases.

## Verification and rollback

Verify frontend `/api/site/config` and admin `/admin-api/site/config` resolve to `huijing`,
HTTPS validates for all four hostnames, and the main site's identity remains
unchanged. Compare model/price/recharge counts against the source, verify
payment return/notify URLs, and confirm new tenant business tables are empty.
Paid image generation and real payments require a separate deliberate test.

## Deployment record — 2026-11-04 (Asia/Shanghai)

- Created tenant ID `12`; the main tenant remains ID `1` (`main`, `艺源`).
- Cloudflare zone is active, with nameservers `arushi.ns.cloudflare.com` and
  `leonidas.ns.cloudflare.com`; Spaceship delegation and all four A records verified.
- Public frontend and admin return HTTP 200 and identify tenant `huijing`.
  The apex and `www` hostnames redirect to `art`, and HTTPS validates for all four.
- Certificate expires on 2027-02-01; Certbot renewal is scheduled with the
  Nginx validation/reload deploy hook.
- Copied 27 models (13 active), 1,537 price versions (1,108 active), and 13
  recharge plans (none active), matching the main-site template. Recharge plans
  remain disabled as inherited; no live payment or paid generation was tested.
- Users, orders, and tasks were empty immediately after provisioning.
- Private configuration backup: `/data/backups/image2/pre-huijing-config-20261104.dump`.

To withdraw this site, disable only its site configuration and new Nginx entry.
Do not restore a shared database backup over other tenants' subsequent writes,
remove existing DNS records, or delete a tenant that has acquired business data.

## User-domain cutover

The user-facing canonical domain is `art.hzhjai.com`. Expand the existing
certificate before enabling its HTTPS entry. For the brief configuration
cutover, enable `image2-huijing-user-maintenance.conf`, validate/reload Nginx,
and verify public HTTP 503 with Retry-After. Back up `site_configs` and
`payment_configs`, then run `scripts/move-huijing-frontend.py` inside the
admin container (dry-run first, then `--apply`). This atomically updates only
tenant 12 frontend and payment URLs with an audit record. Restore the symlink
to `image2-huijing-v3.conf`, validate/reload, and verify tenant identity and
redirects. Shared application containers are not replaced or restarted.
