from ..config import SETTINGS
from .base import JudgeVerdict, Provider, Usage
from .offline import OfflineProvider

_cache: dict[str, object] = {}


def get_provider(name: str | None = None):
    """Return the configured provider, falling back to offline if the live one
    cannot be constructed. Falling back is logged, never silent."""
    name = name or SETTINGS.provider
    if name in _cache:
        return _cache[name]
    provider: object
    if name == "gemini":
        try:
            from .gemini import GeminiProvider
            provider = GeminiProvider(
                api_key=SETTINGS.gemini_api_key,
                judge_model=SETTINGS.judge_model,
                embed_model=SETTINGS.embed_model,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[controlplane] gemini provider unavailable ({exc}); using offline provider")
            provider = OfflineProvider()
    else:
        provider = OfflineProvider()
    _cache[name] = provider
    return provider


__all__ = ["get_provider", "Provider", "Usage", "JudgeVerdict", "OfflineProvider"]
