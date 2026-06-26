"""
scoring — deterministic 10-year cardiovascular risk engines.

Three accredited models, each exposing a `score(inputs: dict) -> ScoreResult`:

    qrisk3  QRISK3-2017      UK,      ages 25-84
    score2  SCORE2/SCORE2-OP Europe,  ages 40-89
    ascvd   Pooled Cohort Eq US,      ages 40-79

Every score is computed here in plain Python. The language model NEVER computes
or alters a score — it only explains a result it is handed.
"""
from . import qrisk3, score2, ascvd
from .common import BANDS, ScoreResult

MODELS = {
    "qrisk3": qrisk3,
    "score2": score2,
    "ascvd": ascvd,
}


def score(model_key: str, inputs: dict) -> ScoreResult:
    """Dispatch to the requested model's score() function."""
    key = model_key.lower()
    if key not in MODELS:
        raise ValueError(f"Unknown model '{model_key}'. Choose one of {list(MODELS)}.")
    return MODELS[key].score(inputs)


__all__ = ["score", "MODELS", "BANDS", "ScoreResult", "qrisk3", "score2", "ascvd"]
