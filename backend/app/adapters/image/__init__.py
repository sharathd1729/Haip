"""Image-generation adapter registry (Marketing Studio, opt-in per tenant).

Every model is listed with its licence status. A model is usable only if `enabled` is true: commercial use cleared on
the provider's own terms AND a hosted endpoint confirmed against the live API. Checked 18 Oct 2026:

| model | licence / terms | hosted endpoint | enabled |
|---|---|---|---|
| gemini-3.1-flash-lite-image (DEFAULT) | Gemini API paid tier (Google API terms); images carry Google's SynthID watermark | generativelanguage.googleapis.com, verified with a real image (sibling 3.1 flash image: 15 s) | yes |
| flux.1-schnell | "ready for commercial use" (Apache-2.0) | ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell (live 422 on bad size) | yes |
| qwen-image | "commercial and non-commercial" (Apache-2.0) | not found: guessed paths return 404 | no, until verified |
| stable-diffusion-3.5-large | "ready for non-commercial use"; commercial needs a Stability AI licence | not checked | no: licence |
| flux.1-dev | "non-commercial use only" | n/a | never |

Callers use get_model(key); it raises ImageModelBlocked for anything not enabled, with the reason.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ImageModel:
    key: str
    label: str
    provider: str
    path: Optional[str]                      # provider path, e.g. "black-forest-labs/flux.1-schnell"
    enabled: bool
    licence: str
    blocked_reason: Optional[str] = None
    sizes: dict = field(default_factory=dict)   # shape -> (width, height) for NVIDIA, or aspect ratio "4:5" for Gemini
    # Price per 1M tokens (USD), from the provider's price page, used only for the cost estimate stored with usage.
    price_in: float = 0.0
    price_out_image: float = 0.0
    price_out_text: float = 0.0
    steps: Optional[int] = None


# Sizes FLUX.1-schnell accepted on a live request (its 422 lists heights 768..1344 in steps of 64).
_FLUX_SIZES = {"square": (1024, 1024), "portrait": (896, 1152), "story": (768, 1344), "landscape": (1344, 768)}

# Gemini aspect ratios for the Studio shapes (the API accepts 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9).
_GEMINI_ASPECTS = {"portrait": "4:5", "square": "1:1", "story": "9:16", "landscape": "16:9"}

DEFAULT_MODEL = "gemini-3.1-flash-lite-image"

MODELS: dict[str, ImageModel] = {
    # ai.google.dev/gemini-api/docs/pricing (18 Oct 2026): input $0.25, image output $30, text/thinking output $1.50
    # per 1M tokens; a 1K image is 1,120 tokens, about $0.034. No free tier for image models.
    "gemini-3.1-flash-lite-image": ImageModel(
        key="gemini-3.1-flash-lite-image", label="Gemini Flash Lite Image", provider="gemini",
        path="gemini-3.1-flash-lite-image", enabled=True,
        licence="Gemini API paid tier, Google API terms; output carries an invisible SynthID watermark",
        sizes=_GEMINI_ASPECTS, price_in=0.25, price_out_image=30.0, price_out_text=1.5),
    "flux.1-schnell": ImageModel(
        key="flux.1-schnell", label="FLUX.1 schnell (NVIDIA, often slow)", provider="nvidia", path="black-forest-labs/flux.1-schnell",
        enabled=True, licence="Apache-2.0; build.nvidia.com: ready for commercial use", sizes=_FLUX_SIZES, steps=4),
    "qwen-image": ImageModel(
        key="qwen-image", label="Qwen-Image (good with text)", provider="nvidia", path=None, enabled=False,
        licence="Apache-2.0; build.nvidia.com: commercial and non-commercial use",
        blocked_reason="Hosted endpoint not confirmed yet; enable once a live request succeeds."),
    "stable-diffusion-3.5-large": ImageModel(
        key="stable-diffusion-3.5-large", label="Stable Diffusion 3.5 Large", provider="nvidia", path=None, enabled=False,
        licence="build.nvidia.com: ready for non-commercial use; commercial use needs a Stability AI licence",
        blocked_reason="Not licensed for commercial use on the NVIDIA catalog."),
    "flux.1-dev": ImageModel(
        key="flux.1-dev", label="FLUX.1 dev", provider="nvidia", path=None, enabled=False,
        licence="build.nvidia.com: non-commercial use only",
        blocked_reason="Non-commercial licence. Never used in HAIP."),
}


class ImageModelBlocked(Exception):
    pass


class ImageGenError(Exception):
    """A generation failure. `transient` = safe to retry (timeout, 429, 5xx, still queued)."""

    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


def estimate_cost_usd(model: ImageModel, input_tokens: int, image_tokens: int, text_tokens: int) -> float:
    """Cost estimate from the provider's reported token counts and the list prices above (not an invoice)."""
    return round((input_tokens * model.price_in + image_tokens * model.price_out_image
                  + text_tokens * model.price_out_text) / 1_000_000, 6)


def get_model(key: str) -> ImageModel:
    model = MODELS.get(key)
    if model is None:
        raise ImageModelBlocked(f"Unknown image model: {key}")
    if not model.enabled:
        raise ImageModelBlocked(model.blocked_reason or f"{model.label} is not available.")
    return model


def generate(model: ImageModel, prompt: str, shape: str, seed: Optional[int] = None) -> tuple[bytes, dict]:
    """Return (image bytes, provenance). Raises ImageGenError."""
    if shape not in model.sizes:
        raise ImageGenError(f"{model.label} does not support the {shape!r} shape.", transient=False)
    if model.provider == "nvidia":
        from app.adapters.image.nvidia import generate as nvidia_generate
        return nvidia_generate(model, prompt, *model.sizes[shape], seed=seed)
    if model.provider == "gemini":
        from app.adapters.image.gemini import generate as gemini_generate
        return gemini_generate(model, prompt, model.sizes[shape])
    raise ImageGenError(f"No adapter for provider {model.provider}", transient=False)
