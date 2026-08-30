import hashlib
import threading

from ..config import SETTINGS
from .base import JudgeVerdict, Provider, Usage
from .offline import OfflineProvider


class CachedEmbeddings:
    """Process-local embedding cache.

    Source documents repeat on almost every request in a real deployment - the
    same policy wording, the same knowledge-base article, thousands of times a
    day. Embedding them once instead of once per request is the single largest
    latency win available, and it costs nothing but memory.
    """

    def __init__(self, inner, max_items: int = 4096):
        self._inner = inner
        self._cache: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self.max_items = max_items
        self.hits = 0
        self.misses = 0

    @property
    def name(self) -> str:
        return self._inner.name

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        keys = [self._key(t) for t in texts]
        out: list[list[float] | None] = [None] * len(texts)
        missing_idx: list[int] = []
        with self._lock:
            for i, k in enumerate(keys):
                hit = self._cache.get(k)
                if hit is not None:
                    out[i] = hit
                    self.hits += 1
                else:
                    missing_idx.append(i)
                    self.misses += 1
        if missing_idx:
            fresh = self._inner.embed([texts[i] for i in missing_idx])
            with self._lock:
                for i, vec in zip(missing_idx, fresh):
                    out[i] = vec
                    if len(self._cache) < self.max_items:
                        self._cache[keys[i]] = vec
        return [v for v in out if v is not None]

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"entries": len(self._cache), "hits": self.hits, "misses": self.misses,
                "hit_rate_pct": round(100 * self.hits / total, 1) if total else 0.0}

    def __getattr__(self, item):
        return getattr(self._inner, item)

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
    provider = CachedEmbeddings(provider)
    _cache[name] = provider
    return provider


__all__ = ["get_provider", "Provider", "Usage", "JudgeVerdict", "OfflineProvider"]
