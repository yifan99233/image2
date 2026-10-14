#!/usr/bin/env bash
set -euo pipefail

FLAG_PATH="${IMAGE2_MAINTENANCE_FLAG:-/var/run/image2-maintenance.flag}"
PAGE_PATH="${IMAGE2_MAINTENANCE_PAGE:-/var/www/image2-maintenance/maintenance.html}"

usage() {
  echo "Usage: $0 on|off|status" >&2
  exit 2
}

case "${1:-}" in
  on)
    install -d -m 0755 "$(dirname "$PAGE_PATH")"
    if [[ -f "$(dirname "$0")/../user-web/public/maintenance.html" ]]; then
      install -m 0644 "$(dirname "$0")/../user-web/public/maintenance.html" "$PAGE_PATH"
    fi
    touch "$FLAG_PATH"
    ;;
  off)
    rm -f "$FLAG_PATH"
    ;;
  status)
    if [[ -f "$FLAG_PATH" ]]; then echo "maintenance=on"; else echo "maintenance=off"; fi
    exit 0
    ;;
  *) usage ;;
esac

if command -v nginx >/dev/null 2>&1; then
  nginx -t
  systemctl reload nginx
fi
echo "maintenance=$1"
