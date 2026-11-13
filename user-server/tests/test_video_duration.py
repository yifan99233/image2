import pytest

from app.core.exceptions import BusinessError
from app.services.image_generation import GenerationModelConfig, _video_request_bodies
from app.services.video_duration import normalize_video_duration_seconds


@pytest.mark.parametrize("model", ["muse-video", "muse-video-cdn"])
@pytest.mark.parametrize("seconds", [1, 10, 30, 60])
def test_muse_duration_survives_upstream_serialization(model, seconds):
    config = GenerationModelConfig("gateway", "Gateway", "https://example.test/v1", "api", "test", "bearer", 900, model)
    bodies = _video_request_bodies(config, "video", "720p", str(seconds), [], "16:9")
    assert bodies
    assert all(int(body.get("duration", body.get("seconds"))) == seconds for body in bodies)


@pytest.mark.parametrize("value", ["0", "-1", "61", "1.5", "30:60", "abc", "30sec"])
def test_rejects_invalid_muse_duration(value):
    with pytest.raises(BusinessError):
        normalize_video_duration_seconds(value, "muse-video")


def test_other_contracts_keep_existing_limit():
    assert normalize_video_duration_seconds("15s", "grok-imagine-video") == 15
    with pytest.raises(BusinessError):
        normalize_video_duration_seconds("60", "grok-imagine-video")
