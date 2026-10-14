# Include this file inside each public HTTPS server block. The release script
# creates the flag before replacing containers and removes it after health checks.
if (-f /var/run/image2-maintenance.flag) { return 503; }
error_page 503 =200 @image2_maintenance;

location @image2_maintenance {
    root /var/www/image2-maintenance;
    try_files /maintenance.html =503;
    add_header Cache-Control "no-store" always;
}
