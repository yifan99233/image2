from app.api.endpoints.admin_data import normalized_image_model_payload
from app.schemas.image_model import AdminImageModelCreate


def test_model_payload_persists_disable_retry():
    payload = AdminImageModelCreate(
        provider_name="内部图片服务",
        provider_code="internal-image",
        base_url="https://example.test/v1",
        name="GPT Image",
        code="gpt-image",
        vendor_model="gpt-image-2",
        capability_type="image",
        image_capabilities=["text_to_image"],
        disable_retry=True,
    )

    normalized = normalized_image_model_payload(payload)

    assert normalized["disable_retry"] is True
