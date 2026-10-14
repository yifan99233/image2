#!/usr/bin/env python3
"""Sync stored image URLs to the configured MinIO public endpoint.

This script is intended to run after importing SQL data into a new environment.
It reads `.env`, then updates `image_assets.url` and matching `image_tasks`
input/output URLs from `storage_key` using:

    USER_MINIO_PUBLIC_ENDPOINT / USER_MINIO_BUCKET
    USER_DATABASE_URL / ADMIN_DATABASE_URL / DATABASE_URL
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(values: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if os.getenv(key):
            return os.getenv(key)
        if values.get(key):
            return values[key]
    return None


def parse_database_url(url: str) -> tuple[str, str, str, str, str]:
    parsed = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")
    if not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise ValueError("Database URL must include username, host, and database name")
    return (
        parsed.hostname,
        str(parsed.port or 5432),
        parsed.username,
        parsed.password or "",
        parsed.path.lstrip("/"),
    )


def main() -> int:
    values = load_dotenv()
    database_url = env_value(values, "DATABASE_URL", "USER_DATABASE_URL", "ADMIN_DATABASE_URL")
    public_endpoint = env_value(values, "USER_MINIO_PUBLIC_ENDPOINT", "MINIO_PUBLIC_ENDPOINT")
    bucket = env_value(values, "USER_MINIO_BUCKET", "MINIO_BUCKET")

    if not database_url:
        print("Missing DATABASE_URL/USER_DATABASE_URL/ADMIN_DATABASE_URL", file=sys.stderr)
        return 2
    if not public_endpoint:
        print("Missing USER_MINIO_PUBLIC_ENDPOINT/MINIO_PUBLIC_ENDPOINT", file=sys.stderr)
        return 2
    if not bucket:
        print("Missing USER_MINIO_BUCKET/MINIO_BUCKET", file=sys.stderr)
        return 2

    host, port, user, password, database = parse_database_url(database_url)
    public_base = f"{public_endpoint.rstrip('/')}/{bucket.strip('/')}/"
    sql = """
BEGIN;

UPDATE image_assets
SET url = :'public_base' || storage_key
WHERE url IS DISTINCT FROM :'public_base' || storage_key;

UPDATE image_tasks task
SET input_image_url = asset.url
FROM image_assets asset
WHERE task.input_image_url IS NOT NULL
  AND task.input_image_url <> asset.url
  AND (
      task.input_image_url = '/uploads/' || asset.storage_key
      OR task.input_image_url LIKE '%' || asset.storage_key
  );

UPDATE image_tasks task
SET output_image_url = asset.url
FROM image_assets asset
WHERE task.output_image_url IS NOT NULL
  AND task.output_image_url <> asset.url
  AND (
      task.output_image_url = '/uploads/' || asset.storage_key
      OR task.output_image_url LIKE '%' || asset.storage_key
  );

COMMIT;

SELECT 'image_assets', regexp_replace(url, '/(images|generated)/.*$', '') AS prefix, count(*)
FROM image_assets
GROUP BY 1, 2
ORDER BY 3 DESC;

SELECT 'image_tasks.input_image_url', regexp_replace(input_image_url, '/(images|generated)/.*$', '') AS prefix, count(*)
FROM image_tasks
WHERE input_image_url IS NOT NULL
GROUP BY 1, 2
ORDER BY 3 DESC;

SELECT 'image_tasks.output_image_url', regexp_replace(output_image_url, '/(images|generated)/.*$', '') AS prefix, count(*)
FROM image_tasks
WHERE output_image_url IS NOT NULL
GROUP BY 1, 2
ORDER BY 3 DESC;
"""
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    command = [
        "psql",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"public_base={public_base}",
    ]
    return subprocess.run(command, cwd=ROOT, env=env, input=sql, text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
