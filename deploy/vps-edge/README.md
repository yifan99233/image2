# shyfai.org VPS edge

This deployment turns the Hong Kong VPS into a cache and reverse-proxy edge:

- `shyfai.org` proxies to `shyfai.com`.
- `<tenant>.shyfai.org` proxies to `<tenant>.shyfai.com`.
- Browser-visible `.org` hosts are preserved.
- The application receives the canonical `.com` Host, Origin, and Referer.
- Vite `/assets/` files and brand icons are cached at the edge.
- APIs, uploads, WebSockets, and SSE are streamed without proxy buffering.

`magic-com-edge.conf` contains dedicated exact-host entries:

- `magic-yy.shyfai.com`, `magic-lqcm.shyfai.com`, and `team.shyfai.com`
  terminate on the VPS.
- Their origins use the fixed production IP with the corresponding `.cn`
  hostname as Host and TLS SNI, so changing the exact `.com` DNS records
  cannot create a loop.

The production origin is `159.195.17.59:443`. The config verifies the origin
certificate with the system CA bundle and sends the mapped `.com` hostname as
TLS SNI.

## Runtime layout

- Repository checkout: `/opt/image2`
- Enabled config symlink:
  `/etc/nginx/conf.d/shyfai-org-edge.conf`
- Certificate:
  `/etc/letsencrypt/live/shyfai.org/fullchain.pem`
- Private key:
  `/etc/letsencrypt/live/shyfai.org/privkey.pem`
- ACME web root: `/var/www/acme`
- Static cache: `/var/cache/nginx/shyfai-org` (maximum 8 GB)

Certificates and private keys are runtime secrets and must never be committed.
Deploy tracked configuration only through Git.
