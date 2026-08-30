from . import bias, cost, grounding, pii, uncertainty
from .base import (BIAS, HALLUCINATION, PRIVACY, UNVERIFIABLE, WASTE, Signal)

DETECTORS = {
    "grounding": grounding.detect,
    "uncertainty": uncertainty.detect,
    "pii": pii.detect,
    "bias": bias.detect,
    "cost": cost.detect,
}

__all__ = ["DETECTORS", "Signal", "HALLUCINATION", "PRIVACY", "BIAS", "WASTE",
           "UNVERIFIABLE", "pii", "bias", "cost", "grounding", "uncertainty"]
