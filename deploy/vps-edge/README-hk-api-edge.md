# Hong Kong API entry points

These are independent aliases, not redirects to another account service.

| Edge hostname | Origin Host and TLS SNI | Pinned origin |
| --- | --- | --- |
| hk-agent3.shyfai.cn | agent3.shyfai.cn | 159.195.17.59:443 |
| hk-yy.shagentai.com | yy.shagentai.com | 159.195.232.157:443 |
| hk-agent.shyfai.com | agent.shyfai.com | 159.195.232.157:443 |

The edge is 43.161.202.24. Alias A records are DNS-only; the original hostnames
retain their existing records. YY and agent use separate TLS keepalive pools
even though they share an origin IP. Requests stream without caching or
automatic upstream retries, including POSTs. Logs omit query strings and auth.

The runtime site is `/etc/nginx/conf.d/zz-hk-api-edge.conf`, installed from the
Git checkout. Backups stay outside every active Nginx include. Validate the
complete configuration and preserve the existing warning set before reloading.

For the initial hk-agent certificate expansion, install only
`hk-agent.bootstrap.conf` alongside the existing site to serve HTTP ACME files
from `/var/www/acme`. Include all three aliases in the `hk-api-edge` certificate.
After issuance, atomically install the expanded TLS site and remove the
temporary bootstrap from the active include set before validating/reloading;
otherwise its port-80 hostname would conflict with the expanded site.

Use webroot renewal and `sh /opt/image2/deploy/vps-edge/reload-hk-api-certificate.sh`
as the deploy hook. Run `test-hk-api-edge.py` with Nginx/OpenSSL/Python available:
it uses isolated loopback HTTPS origins and no production application state.
After rollout, verify DNS, certificate names, API identity, existing aliases,
and request-ID-correlated edge logs proving the actual pinned origin.
