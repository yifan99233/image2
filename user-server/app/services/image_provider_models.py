"""Model identities used by the OpenAI-compatible image adapters."""

OPENAI_IMAGES_API_MODEL_PREFIXES = (
    "gpt-image",
    "grok-imagine-image",
    "agent5-gpt-image",
    "agent5-nano-banana",
    "firefly-gpt-image",
    "firefly-nano-banana",
)

BANANA_IMAGES_API_MODELS = frozenset(
    {
        "gemini-3.1-flash-image",
        "gemini-nano-banana-2.1",
        "gemini-3-pro-image",
        "nano-banana-2-adx1",
        "nano-banana-2.1-adx1",
        "nano-banana-2-adx2",
        "nano-banana-2.1-adx2",
    }
)

MIDJOURNEY_IMAGES_API_MODELS = frozenset({"mj", "mj-adx"})
MIDJOURNEY_OUTPUT_COUNT = 4
MIDJOURNEY_ASPECT_RATIOS = frozenset({"1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"})


def is_midjourney_images_model(model: str) -> bool:
    return (model or "").strip().lower().removesuffix("-cdn") in MIDJOURNEY_IMAGES_API_MODELS


def images_per_generation(model: str) -> int:
    return MIDJOURNEY_OUTPUT_COUNT if is_midjourney_images_model(model) else 1


def is_banana_images_model(model: str) -> bool:
    return (model or "").strip().lower().removesuffix("-cdn") in BANANA_IMAGES_API_MODELS


ADX1_IMAGES_API_MODELS = frozenset({
    "nano-banana-2-adx1", "nano-banana-2.1-adx1",
    "gpt-image-2-adx1", "gpt-image-2.5-flare-adx1", "gpt-image-2.5-sunburst-adx1",
})


def is_adx1_images_model(model: str) -> bool:
    return (model or "").strip().lower().removesuffix("-cdn") in ADX1_IMAGES_API_MODELS

ADX2_IMAGES_API_MODELS = frozenset({
    "nano-banana-2-adx2", "nano-banana-2.1-adx2",
    "gpt-image-2-adx2", "gpt-image-2.5-flare-adx2",
})


def is_adx2_images_model(model: str) -> bool:
    return (model or "").strip().lower().removesuffix("-cdn") in ADX2_IMAGES_API_MODELS
