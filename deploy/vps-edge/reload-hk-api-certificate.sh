#!/bin/sh
set -eu

# Certbot deploy hook: reload only after a successful renewal and config check.
/usr/sbin/nginx -t
/bin/systemctl reload nginx
