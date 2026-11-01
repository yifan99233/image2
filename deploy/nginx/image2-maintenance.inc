# Include this file inside each public HTTPS server block. The release script
# creates the flag before replacing containers and removes it after health checks.
set $image2_maintenance_enabled 0;
if (-f /var/run/image2-maintenance.flag) { set $image2_maintenance_enabled 1; }
# In-flight reference downloads must continue while the application is hidden.
if ($uri ~ "^/image2-assets/") { set $image2_maintenance_enabled 0; }
if ($image2_maintenance_enabled = 1) { return 503; }
error_page 503 @image2_maintenance;

location @image2_maintenance {
    root /var/www/image2-maintenance;
    try_files /maintenance.html =503;
    add_header Cache-Control "no-store" always;
    add_header Retry-After "60" always;
}
