proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $magic_lqcm_cn_hk_edge_host;
proxy_set_header Accept-Encoding "";
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Port 443;

proxy_ssl_server_name on;
proxy_ssl_name $magic_lqcm_cn_hk_edge_host;
proxy_ssl_verify on;
proxy_ssl_verify_depth 5;
proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;

proxy_connect_timeout 15s;
proxy_send_timeout 60s;
proxy_read_timeout 60s;

proxy_cache magic_lqcm_cn_static;
proxy_cache_key "$host$request_uri";
proxy_cache_lock on;
proxy_cache_lock_timeout 10s;
proxy_cache_background_update on;
proxy_cache_use_stale error timeout invalid_header updating http_500 http_502 http_503 http_504;
proxy_cache_valid 200 30d;

proxy_hide_header X-Edge-Cache;
add_header Cache-Control "public, max-age=31536000, immutable" always;
add_header X-HK-Edge-Cache $upstream_http_x_edge_cache always;
add_header X-Edge-Cache $upstream_cache_status always;
add_header X-Acceleration-Edge domestic-hk always;
