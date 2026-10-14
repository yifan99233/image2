# Infinite Canvas source attribution

Source: https://github.com/basketikun/infinite-canvas

Pinned revision: `e856c878e0a34651bb828e28f0af20d71016a7d4`

License: MIT; copyright © 2026 basketikun. See LICENSE.

This directory vendors the upstream React canvas and adapts its host integration,
generation, project storage, and asset picker for image2. It is built separately
and served at `/canvas-app/` inside the authenticated user application.

The `src/integration/` directory contains the image2 integration. Host actions are
handled in `user-web/src/pages/canvas/`; durable projects belong to user-server.
No upstream API credentials are sent to this application. Local Agent, external
plugins, provider configuration, and external analytics are not enabled.

Build through `npm run build` in user-web (install canvas-web dependencies first).
