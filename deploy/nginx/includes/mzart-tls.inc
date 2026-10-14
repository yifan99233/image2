ssl_certificate /etc/letsencrypt/live/mzart.hzpicai.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/mzart.hzpicai.com/privkey.pem;
include /etc/letsencrypt/options-ssl-nginx.conf;
ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
