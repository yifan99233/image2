# Hong Kong API entry points

These are independent aliases, not redirects to another account service.

| Edge hostname | Origin Host and TLS SNI | Pinned origin |
| --- | --- | --- |
| hk-agent3.shyfai.cn | agent3.shyfai.cn | 159.195.17.59:443 |
| hk-yy.shagentai.com | yy.shagentai.com | 159.195.232.157:443 |
| hk-agent.shyfai.com | agent.shyfai.com | 159.195.232.157:443 |
| hk.hzpixai.com | hzpixai.com | 159.195.232.157:443 |

The edge is 43.161.202.24. Alias A records are DNS-only; the original hostnames
retain their existing records. YY and agent use separate TLS keepalive pools
even though they share an origin IP. Requests stream without caching or
automatic upstream retries, including POSTs. Logs omit query strings and auth.

The runtime site is `/etc/nginx/conf.d/zz-hk-api-edge.conf`, installed from the
Git checkout. Backups stay outside every active Nginx include. Validate the
complete configuration and preserve the existing warning set before reloading.

Include all four aliases in the `hk-api-edge` certificate. The current Hong
Kong host is not reachable by the CA on public port 80, so use manual DNS-01
validation with the Cloudflare credential held in the local macOS Keychain.
Only create the requested temporary TXT proof, verify authoritative DNS before
continuing Certbot, then remove the proof created for that validation. Never
copy the Cloudflare API token onto this server.

The hzpixai management entry is `https://hk.hzpixai.com/channels`. Preserve
the request path/query and rewrite canonical login redirects onto the alias.
Authentication remains the origin application's responsibility: anonymous
visitors may be redirected to that same site's login route.

`hk-agent.bootstrap.conf` is an optional HTTP-only challenge site for a future
network where port 80 is publicly reachable; its files use `/var/www/acme`.
After issuance, atomically install the expanded TLS site and remove any
temporary bootstrap from the active include set before validating/reloading;
otherwise its port-80 hostname would conflict with the expanded site.

The deploy hook is `sh /opt/image2/deploy/vps-edge/reload-hk-api-certificate.sh`.
It validates/reloads Nginx; it does not automate manual DNS validation. Renewal
therefore still requires the DNS-01 process unless a separately authorized DNS
auth hook is configured. Run `test-hk-api-edge.py` with Nginx/OpenSSL/Python available:
it uses isolated loopback HTTPS origins and no production application state.
After rollout, verify DNS, certificate names, API identity, existing aliases,
and request-ID-correlated edge logs proving the actual pinned origin.
