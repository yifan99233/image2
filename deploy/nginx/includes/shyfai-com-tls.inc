# Existing V3 wildcard certificate for the shyfai.com tenant hostnames.
ssl_certificate /etc/letsencrypt/live/shyfai.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/shyfai.com/privkey.pem;
include /etc/letsencrypt/options-ssl-nginx.conf;
ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
