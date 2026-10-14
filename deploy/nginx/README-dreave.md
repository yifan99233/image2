# Dreave on V3

Dreave is the existing image2 tenant with site ID 7. Its user and admin hosts
must reach the V3 image2 stack while preserving the public Host header.

The wildcard DNS record for `*.shyfai.com` still belongs to V1, which serves
other applications. Create only these two explicit DNS-only A records, with
TTL 120, after the origin HTTPS checks pass and the DNS change is authorized:

- `magic-dreave.shyfai.com` -> `38.147.104.202`
- `magic-admin-dreave.shyfai.com` -> `38.147.104.202`

Do not change the wildcard record or start the stopped V1 image2 database.

After the reviewed Git commit has been pushed and pulled into
`/data/workspace/image2`, activate the tracked configuration:

```sh
ln -s /data/workspace/image2/deploy/nginx/image2-dreave-v3.conf /etc/nginx/sites-enabled/image2-dreave-v3
nginx -t
systemctl reload nginx
```

The shared TLS include uses V3's existing `*.shyfai.com` certificate. Verify
its SAN coverage and expiry before activation. Probe both origins with
`curl --resolve <hostname>:443:127.0.0.1 https://<hostname>/login` without
turning off certificate validation. Verify the user `/api/site/config`
returns `site_key: Dreave` and `id: 7`; verify the admin login page and its
unauthenticated API boundary. After DNS propagation, repeat using public DNS.

Before the DNS change, removing only the `image2-dreave-v3` symlink and
reloading Nginx rolls back origin activation. After DNS cutover, do not roll
back DNS to the stopped V1 service without a separate recovery plan.
