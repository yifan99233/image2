# user-server

User-facing FastAPI service for registration, login, current-user auth, and later user business APIs.

## Setup

```bash
cd user-server
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Local development reads the repository root `.env` first. Keep database and
MinIO in that single file; if you run the server outside Docker, change the host
values in `.env` to addresses reachable from your machine.

## Run

```bash
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/healthz
```

## Database

```bash
alembic upgrade head
```

`DATABASE_URL` is loaded from the shared `.env`.
