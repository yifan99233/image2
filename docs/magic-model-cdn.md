# Magic model CDN delivery

`MODEL_CDN_CONFIG_JSON` is private runtime configuration. It contains `site_id`, `model_ids`, `cdn_key`, `public_base_url`, `key_prefix`, `endpoint`, `region`, `bucket`, `access_key`, and `secret_key`. Never commit its values. Empty configuration preserves existing behavior. The model IDs and site ID explicitly scope both reference uploads and output delivery.

For scoped Images API models, Magic sends `cdn_key` and the NewAPI-compatible `gateway_cdn_key`, requests URL output, and accepts only HTTPS URLs in the configured CDN prefix. Set these models' `storage_mode` to `native`. The final image is neither downloaded nor uploaded by Magic; the asset has no local/R2 copy. Missing or unexpected URLs are an explicit delivery error, not a silent re-upload or regenerated image. V4 still owns 1K generation and optional 2K/4K upscaling.

`POST /uploads/images` with `model_id` writes scoped references to `<prefix>/inputs/<user>/<uuid>.<ext>` through S3, without a local backup. Model/site availability is checked first. The normal image-edit UI supplies the selected model ID. Existing assets and unrelated uploads are unchanged. Existing reference URLs may still be read to assemble the upstream multipart image edit request.

V4 must normalize `gateway_cdn_key`, authorize the CDN key for the NewAPI upstream tenant, and use `default_cdn_key` instead of a forced `cdn_key` override on these aliases. An explicit request key wins over a default, while legacy callers retain the previous default. Conflicting explicit keys are rejected. No concurrency or upscale budgets change.

Deployment: enable and verify Magic maintenance, pause dispatch and drain active tasks, preserve queues, deploy via Git, configure runtime and native storage mode, verify uploads and a real edit, then restore public traffic. Keep prior images, models' storage modes and private runtime configuration for rollback.

Retention is separate from URL storage. The shared OSS bucket currently has no completed-object expiration rule. Do not apply a bucket-wide short expiry; configure only the dedicated prefix when enabling retention. A seven-day history filter does not delete OSS objects.

FF video CDN (2026-11-04): add a separate site/model scope with
`upload_video_results: true` and prefix `magic/videos`, reusing the existing ADX
S3 bucket and public origin. Retain `storage_mode=local` for the scoped FF models:
this explicit upload scope takes precedence for MP4 results, while disabling the
scope restores local storage. Unlike ADX image generation, V4 does not upload these
videos directly: Magic downloads the accepted video's content and uploads it to
S3 without another generation request. Normal execution and stale-job resume both
use the same storage path. Keys include user ID, task ID and SHA-256, making transfer
retries deterministic; asset metadata records actual bytes and hash. Multipart
uploads use sequential 5 MiB parts without copying the entire source buffer.
Failures remain errors with the original provider ID preserved. Existing objects
are not migrated or deleted. Bucket retention remains unchanged.

Validation: CDN scope/unchanged ADX tests, MP4 integrity, deterministic retry,
upload failure sanitization, and 500 concurrent result-storage calls with 8 MiB
fixture bytes and a mock S3 target. This checks application scheduling and byte
integrity, not 500 real CDN uploads or upstream generation throughput. The existing
six image-generation test failures are unchanged from the prior release.
