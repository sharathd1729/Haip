from app.adapters.ivr.base import IVRAdapter, CallWebhookPayload
from app.adapters.ivr.callerdesk import CallerDeskAdapter
from app.adapters.ivr.acefone import AcefoneAdapter


def get_ivr_adapter(provider: str) -> IVRAdapter:
    adapters = {
        "callerdesk": CallerDeskAdapter,
        "acefone": AcefoneAdapter,
    }
    cls = adapters.get(provider.lower())
    if not cls:
        raise ValueError(f"Unknown IVR provider: {provider}")
    return cls()
