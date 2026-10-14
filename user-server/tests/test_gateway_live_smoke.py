from __future__ import annotations

import os

import httpx
import pytest


def _required_smoke_setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for the live gateway smoke test")
    return value


async def test_live_gateway_lists_and_invokes_configured_model():
    base_url = _required_smoke_setting("GATEWAY_SMOKE_BASE_URL").rstrip("/")
    api_key = _required_smoke_setting("GATEWAY_SMOKE_API_KEY")
    model = os.environ.get("GATEWAY_SMOKE_MODEL", "gpt-5.6-sol").strip()
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        models_response = await client.get(f"{base_url}/models", headers=headers)
        assert models_response.status_code == 200, models_response.text[:500]
        model_ids = {
            item.get("id")
            for item in models_response.json().get("data", [])
            if isinstance(item, dict)
        }
        assert model in model_ids

        response = await client.post(
            f"{base_url}/responses",
            headers=headers,
            json={
                "model": model,
                "input": "只回复：OK",
                "stream": False,
                "max_output_tokens": 16,
            },
        )
        assert response.status_code == 200, response.text[:500]
        payload = response.json()
        assert payload.get("status") == "completed"
        assert payload.get("model") == model
        assert payload.get("error") is None
