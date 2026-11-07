import os
from urllib.parse import urlparse

test_database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
if not test_database_url:
    raise RuntimeError("TEST_DATABASE_URL is required for tests; never point this test suite at production.")

parsed_database_url = urlparse(test_database_url)
database_name = parsed_database_url.path.rsplit("/", 1)[-1].lower()
if "test" not in database_name:
    raise RuntimeError(f"Refusing to run destructive tests against non-test database: {database_name or '<unknown>'}")

os.environ["DATABASE_URL"] = test_database_url
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough")
os.environ.setdefault("ALLOW_PLAINTEXT_PASSWORD", "true")
os.environ.setdefault("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "100")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
