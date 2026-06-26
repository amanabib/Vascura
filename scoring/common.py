"""
scoring/common.py — shared types and the 0-100 / six-band mapping.

THE 0-100 SCORE AND THE SIX BANDS (transparent, consistent across all models)
----------------------------------------------------------------------------
Every model outputs a 10-year risk as a PERCENTAGE. We keep things honest by
making the 0-100 "score" simply that percentage, rounded and capped at 100.
So a score of 12 means "an estimated 12% chance of a cardiovascular event in
the next 10 years" — nothing is invented or rescaled.

We then place the percentage into one of six fixed bands. The band EDGES were
chosen to line up with real clinical reference points so the bands stay
meaningful across models:

    Low risk            : < 5%      (ASCVD "low" line)
    Relatively low risk : 5  - <7.5%(ASCVD "borderline" line at 7.5)
    Moderate risk       : 7.5- <10% (QRISK3 / NICE statin-discussion line at 10)
    Relatively high risk: 10 - <20% (ASCVD "intermediate" up to its 20 line)
    High risk           : 20 - <30%
    Very high risk      : >= 30%

The bands are a presentation convenience for a clean, consistent UI. Each model
ALSO carries its own clinical reference points (see clinical_note per model),
because what counts as "high" really is model- and age-specific. SCORE2 in
particular uses age-specific thresholds, surfaced separately.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

# (label, lower_inclusive, upper_exclusive)
BANDS = [
    ("Low risk", 0.0, 5.0),
    ("Relatively low risk", 5.0, 7.5),
    ("Moderate risk", 7.5, 10.0),
    ("Relatively high risk", 10.0, 20.0),
    ("High risk", 20.0, 30.0),
    ("Very high risk", 30.0, float("inf")),
]


def risk_to_score_and_band(risk_percent: float):
    """Return (score_0_100:int, band_label:str, band_index:int)."""
    p = max(0.0, min(100.0, float(risk_percent)))
    score = int(round(p))
    for i, (label, lo, hi) in enumerate(BANDS):
        if lo <= p < hi:
            return score, label, i
    return score, BANDS[-1][0], len(BANDS) - 1


@dataclass
class Factor:
    label: str
    direction: str          # "raises" | "lowers" | "neutral"
    # how many percentage points this factor adds/removes vs its neutral value
    delta_points: float
    detail: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class ScoreResult:
    model: str                       # "QRISK3" | "SCORE2" | "ASCVD"
    model_label: str
    risk_percent: float              # 10-year risk, %
    score_0_100: int
    band: str
    band_index: int
    in_valid_age_range: bool
    age_min: int
    age_max: int
    clinical_note: str               # model-specific reference points for THIS result
    key_factors: list                # list[Factor] -> dicts
    extras: dict = field(default_factory=dict)     # e.g. QRISK3 heart age / relative risk
    missing_inputs: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    inputs_used: dict = field(default_factory=dict)
    estimated_inputs: list = field(default_factory=list)  # population-average substitutions

    def to_dict(self):
        d = asdict(self)
        d["key_factors"] = [f if isinstance(f, dict) else f.to_dict() for f in self.key_factors]
        return d


def leave_one_out(score_fn: Callable[[dict], float],
                  base_inputs: dict,
                  factors: list) -> list:
    """
    Deterministic, model-grounded "what is driving this result".

    For each factor we recompute the 10-year risk with that single input reset to
    a neutral/reference value (non-smoker, no condition, average cholesterol, etc.)
    while holding everything else at the person's actual values. The difference
    (actual_risk - neutral_risk) is how many percentage points that factor adds
    (positive) or removes (negative). Factors are returned ranked by magnitude.

    `factors` is a list of dicts: {key, label, neutral, detail_when_set?}
    """
    actual = score_fn(base_inputs)
    out = []
    for spec in factors:
        key = spec["key"]
        if key not in base_inputs:
            continue
        neutral_val = spec["neutral"]
        if base_inputs[key] == neutral_val:
            continue  # factor already at neutral -> not contributing
        probe = dict(base_inputs)
        probe[key] = neutral_val
        without = score_fn(probe)
        delta = actual - without
        if abs(delta) < 0.05:
            continue
        out.append(Factor(
            label=spec["label"],
            direction="raises" if delta > 0 else "lowers",
            delta_points=round(delta, 1),
            detail=spec.get("detail", ""),
        ))
    out.sort(key=lambda f: abs(f.delta_points), reverse=True)
    return out
