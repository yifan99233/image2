proxy_http_version 1.1;
proxy_set_header Host $magic_lqcm_cn_hk_edge_host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Port 443;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $magic_lqcm_cn_connection_upgrade;

proxy_ssl_server_name on;
proxy_ssl_name $magic_lqcm_cn_hk_edge_host;
proxy_ssl_verify on;
proxy_ssl_verify_depth 5;
proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;

proxy_connect_timeout 15s;
proxy_send_timeout 600s;
proxy_read_timeout 600s;
proxy_request_buffering off;
proxy_buffering off;
proxy_cache off;

proxy_redirect https://magic-lqcm.shyfai.com/ https://magic-lqcm.shyfai.cn/;
proxy_redirect https://magic-lqcm-admin.shyfai.org/ https://magic-lqcm-admin.shyfai.cn/;
proxy_redirect https://team.shyfai.com/ https://team.shyfai.cn/;
proxy_cookie_domain shyfai.com shyfai.cn;
proxy_cookie_domain .shyfai.com .shyfai.cn;
proxy_cookie_domain shyfai.org shyfai.cn;
proxy_cookie_domain .shyfai.org .shyfai.cn;

proxy_hide_header X-Edge-Cache;
add_header X-HK-Edge-Cache $upstream_http_x_edge_cache always;
add_header X-Acceleration-Edge domestic-hk always;
