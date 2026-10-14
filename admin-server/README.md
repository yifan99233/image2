# admin-server

Management API for the image AI editing platform. It exposes only `/admin/**`
business endpoints plus `/healthz`.

## Setup

```bash
cd admin-server
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
```

## Database

```bash
alembic upgrade head
python scripts/seed_super_admin.py
```

## Run

```bash
uvicorn app.main:app --reload
```

## OpenAgent release upload

The admin OpenAgent release page requests `/admin/openagent/upload-token` before
uploading a package. The server signs a Qiniu upload token from these settings:

```env
QINIU_ACCESS_KEY=
QINIU_SECRET_KEY=
QINIU_BUCKET=
QINIU_CDN_BASE_URL=
QINIU_UPLOAD_HOST=https://upload.qiniup.com
OPENAGENT_RELEASE_PREFIX=openagent/releases
```

`QINIU_CDN_BASE_URL` should be the public download domain, for example
`https://download.example.com`. Uploaded package keys are generated under
`OPENAGENT_RELEASE_PREFIX`.

## Verify

```bash
pytest
```

Useful endpoints:

- `GET /healthz`
- `GET /admin/auth/public-key`
- `POST /admin/auth/login`
- `GET /admin/auth/me`
- `PATCH /admin/auth/me/password`
