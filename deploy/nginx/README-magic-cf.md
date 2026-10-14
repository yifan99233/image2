# Magic Cloudflare test entry on V3

`https://magic-cf.shyfai.cn/login` serves the existing image2 user application.
The original `magic.shyfai.cn` hostname remains DNS-only for comparison.

Cloudflare DNS: `magic-cf.shyfai.cn`, type `A`, content `38.147.104.202`,
proxy enabled, automatic TTL. Use Full (strict) encryption where configured;
the origin uses the existing `*.shyfai.cn` certificate.

After committing locally, pushing, and pulling the commit on V3:

```bash
ln -s /data/workspace/image2/deploy/nginx/image2-magic-cf-v3.conf /etc/nginx/sites-enabled/image2-magic-cf
nginx -t
systemctl reload nginx
```

The public endpoint uses HTTPS port 443. Nginx sends frontend and API requests
to `127.0.0.1:3002` and stored image requests to `127.0.0.1:9002`, using the
shared image2 proxy profile. No application container rebuild is needed.

Verify the origin first with `curl --resolve magic-cf.shyfai.cn:443:38.147.104.202
https://magic-cf.shyfai.cn/login`, then check the public URL for a `cf-ray`
response header. Validate `/api/healthz`, `/api/site/config`, and the JS/CSS
referenced by the login page through the public hostname.
