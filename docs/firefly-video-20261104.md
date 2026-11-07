# FF video through Agent and V4

Main Magic site uses the dedicated `firefly-video-agent` provider, whose key and
URL are copied from the existing Agent provider without changing its image models.
Seven FF models are text-to-video only, with 720p/1080p and 16:9,9:16,1:1.
Veo/Luma durations are 4/8 seconds; Kling durations are 5/10/15 seconds.
`firefly-video-main.sql` registers their options and resolution/duration prices.
Main wallet conversion was checked: 1 CNY buys one Agent balance unit, displayed
as 100 Magic credits. Price is a fixed 30-credit surcharge with zero base cost,
so existing VIP discounts do not change the requested CNY 0.30 per video.

The FF path posts once to `/v1/videos`. Accepted IDs are persisted before polling;
poll failures or download failures never probe another generation endpoint or
body. Download failures propagate rather than reporting an empty successful asset.
The configured local storage mode copies MP4 bytes to Magic's existing durable
storage; provider URLs expire after three hours and must not be used as permanent
Magic history URLs. Model timeout is 900 seconds and automatic regeneration is
disabled. Existing tasks with provider IDs use the existing resume path.

Validation: four FF regressions pass. The full image-generation test module has
82 passing tests and six pre-existing failures, reproduced on unmodified e1a6a15
(78 passing, same six failures). No production database is used in these tests.

Release only after Agent/V4 validation. Use the standard Magic maintenance gate,
verify public 503/Retry-After, drain the dispatcher with advisory lock 1515143748,
replace only user-server from the pulled Git revision, apply the main-only SQL,
verify catalog/options/pricing/storage internally, resume and remove maintenance.
Keep prior image/config and a protected database configuration snapshot for rollback.

## Confirmed tiers (supersedes the initial matrix above)

Apply `scripts/firefly-video-tiers.sql` after the FF and V4 validators and Agent
flat billing support Omni Flash. Public main-site models are Veo 3.1 / Fast / Lite
(4/6/8 seconds, 720p/1080p), Gemini Omni Flash (each integer 3–10 seconds, 720p),
Kling 3.0 (each integer 3–15 seconds, 720p), and Luma Ray3.14 (5/10 seconds, 720p).
Kling V3 Omni is a separate model, not Gemini Omni Flash. Legacy Kling Omni and
Ray3 identities remain available for ongoing jobs but are hidden from the public
catalog. All 41 public combinations cost 30 credits. The matrix SQL was applied
twice against an isolated local PostgreSQL schema, verifying exact options, flat
prices and repeatability. Add the new Omni model ID to the existing FF-only video
CDN scope; preserve other site/model scopes and existing prices/tasks.
