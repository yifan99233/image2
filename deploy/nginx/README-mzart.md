# mzart on V3

The `mzart` tenant uses `mzart.hzpicai.com` (user),
`mzart-admin.hzpicai.com` (admin), and `mzart-team.hzpicai.com` (team).
The team root redirects to `/mzart/`, which supplies the tenant key to the
existing team frontend and its internal API proxy. Other tenant paths are
not served on this dedicated hostname.

The image2 application and tenant data now run on V3 (`38.147.104.202`) in
`/data/workspace/image2`. The retired V1 application containers must stay stopped.
`image2-mzart-v3.conf` uses V3's Nginx 1.24 syntax and checkout path. Preserve
`Host` when proxying: the site configuration API must resolve `site_key=mzart`
and site ID 9, not the default tenant.

DNS uses three explicit, DNS-only A records pointing to `38.147.104.202`, with
TTL 300. Keep `*.hzpicai.com` unchanged; it may serve unrelated tenants.
Configuration is deployed only through Git. Application containers need no rebuild
or restart, and this change requires no database mutation.

After a clean, fast-forward pull, install a symlink from
`/etc/nginx/sites-enabled/image2-mzart` to
`/data/workspace/image2/deploy/nginx/image2-mzart-v3.conf`.
Before activating it, ensure a valid certificate covering all three names exists
under `/etc/letsencrypt/live/mzart.hzpicai.com/`. Certificates and private keys are
runtime files and must never be committed. When migrating an existing certificate,
preserve its chain and key, register its renewal configuration against an existing
local ACME account, and verify renewal on the new host after DNS cutover.

For a fresh certificate, use the HTTP bootstrap configuration with V3's checkout
path, then issue through the existing webroot:

```sh
certbot certonly --webroot -w /var/www/html --non-interactive --agree-tos \
  --cert-name mzart.hzpicai.com \
  -d mzart.hzpicai.com -d mzart-admin.hzpicai.com -d mzart-team.hzpicai.com
```

Run `nginx -t` before reloading. Verify the new origin with `curl --resolve`
for all three HTTPS names before switching DNS. Check the user `/api/site/config`
and admin `/admin-api/site/config` responses resolve the mzart tenant; verify the
team `/mzart/` frontend and tenant API routing. Test static assets and ensure a
foreign team path still returns 404.

After DNS propagation, repeat the public checks and run
`certbot renew --dry-run --cert-name mzart.hzpicai.com`. The existing Certbot timer
and Nginx reload deploy hook maintain renewal. Payment notify/return URLs and
stored image links retain their existing public hostnames.

The original `image2-mzart.conf` documents the retired V1 entry. Keep it intact
for migration reference. Removing only the new V3 Nginx symlink disables the new
entry; never stop shared image2 containers or delete tenant data to roll it back.
