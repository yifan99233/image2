# Midjourney image batches

Midjourney via the OpenAI Images adapter uses `POST /v1/images/generations`.
A generation always requests `n=4` and receives four independent images. The
current supported options are v7, normal mode, fast speed and the seven standard
ratios (1:1, 4:3, 3:4, 16:9, 9:16, 3:2, 2:3). Pixel size, GPT quality and Banana
resolution are not Midjourney parameters. Image editing is currently unsupported.

One Magic task represents one upstream generation. Its four outputs are saved
under `image_tasks.output_image_assets`; the legacy primary output remains the
cover. Task creation and billing still run once. The configured internal MJ price
is 6 credits per group, rather than per returned image. The catalog capability
`images_per_generation` tells clients to label the quantity as groups. Choosing
multiple groups deliberately creates multiple independent paid generations.

Task polling, works and gallery serialization return every output. ZIP exports
include all outputs with distinct names. Storage follows the model's storage mode;
`third_party` uses Magic's own Qiniu CDN with ordinary upstream model `mj`.
The Magic provider's New API key must have its R2 default disabled: the ADX
contract rejects `r2_url_mode`. No gateway CDN alias is required.

Migration `20261022_0100` adds a nullable output manifest and builds its GIN index
concurrently. Historical one-image tasks fall back to existing columns. Retention
matches every output, and collecting a group protects all its generated objects.

Deploy through Git only. Build both user images first, retaining the previous
images. Before replacing the combined API/worker service, hold the existing
PostgreSQL dispatcher advisory lock (`0x5A4F4244`) from a separate operational
connection; wait for running tasks to finish. Queued tasks remain queued. Release
the lock after migrations and health checks succeed. Never restart active image
generation merely to release this adapter. Previously failed tasks are not replayed.

The Python runtime image uses the committed uv lock and a non-root user. Unit and
PostgreSQL regression checks cover four-image parsing/storage, one-task pricing,
exports, legacy fallback and all-output retention. A real upstream call is separate
from a full Magic/CDN end-to-end check and from any capacity/load validation.
