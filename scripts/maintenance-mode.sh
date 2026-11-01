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
if [[ "$1" == on ]]; then
  # A flag alone cannot prove every public virtual host includes the handler.
  check_dir="$(mktemp -d)"
  trap 'rm -rf "$check_dir"' EXIT
  for host in ${IMAGE2_MAINTENANCE_VERIFY_HOSTS:-magic.shyfai.cn magic.shyfai.com}; do
    for path in / /api/site; do
      verified=false
      # Reload is graceful: give new workers a bounded interval to take over.
      for attempt in {1..10}; do
        status="$(curl --silent --show-error --max-time 20 -D "$check_dir/headers" -o "$check_dir/body" -w '%{http_code}' "https://$host$path")"
        if [[ "$status" == 503 ]] && grep -q 'data-image2-maintenance="true"' "$check_dir/body" && grep -qi '^Retry-After: 60' "$check_dir/headers"; then
          verified=true
          break
        fi
        sleep 1
      done
      if [[ "$verified" != true ]]; then
        echo "Maintenance not verified for $host$path (HTTP $status); flag retained, do not deploy." >&2
        exit 1
      fi
      echo "maintenance_verified=$host$path status=$status"
    done
  done
fi
echo "maintenance=$1"
