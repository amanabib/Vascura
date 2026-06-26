"""
estimate.py — fill in a missing input from population averages.

WHY THIS EXISTS
---------------
A layperson often doesn't know their cholesterol or blood pressure. Rather than
block them, we let them ask the tool to substitute a *typical value for someone
of their age and sex* so they can still explore the model. This is exactly what
QRISK3 itself does internally for missing values.

HONESTY RULES (enforced by callers)
-----------------------------------
* An estimated input makes the result LESS reliable. Every estimated field is
  surfaced to the user and the result carries a prominent "based on estimates"
  warning. The advice layer is told too.
* These are APPROXIMATE population averages by age band and sex, in line with
  published adult health-survey statistics and the population means used by
  tools like QRISK3. They are not a fitted personal model. A real measured value
  should always be preferred when available.
* Where height and weight are known (QRISK3), systolic blood pressure gets a
  small, clearly-bounded adjustment for BMI, since that association is
  well-established in direction. Cholesterol is left on age+sex only, because its
  population association with BMI is too weak to estimate reliably.

Supported fields: systolic_bp, total_chol, hdl, chol_ratio (total:HDL).
"""
from __future__ import annotations
from typing import Optional

# --- age banding ---------------------------------------------------------------
def _band(age: float) -> str:
    if age < 30: return "20s"
    if age < 40: return "30s"
    if age < 50: return "40s"
    if age < 60: return "50s"
    if age < 70: return "60s"
    if age < 80: return "70s"
    return "80+"

# --- approximate population averages by sex and age band -----------------------
# Values reflect typical adult population averages (UK/Western health-survey
# ranges) and are deliberately rounded. They are consistent with the all-ages
# population means used by QRISK3 (male SBP ~129, ratio ~4.3; female SBP ~123,
# ratio ~3.5). Treat as approximate.
_SBP = {  # systolic blood pressure, mmHg
    "male":   {"20s": 121, "30s": 123, "40s": 126, "50s": 130, "60s": 135, "70s": 140, "80+": 143},
    "female": {"20s": 112, "30s": 115, "40s": 120, "50s": 127, "60s": 134, "70s": 140, "80+": 144},
}
_TOTAL_CHOL = {  # total cholesterol, mmol/L
    "male":   {"20s": 4.6, "30s": 5.1, "40s": 5.5, "50s": 5.5, "60s": 5.2, "70s": 4.9, "80+": 4.7},
    "female": {"20s": 4.5, "30s": 4.8, "40s": 5.2, "50s": 5.7, "60s": 5.9, "70s": 5.7, "80+": 5.4},
}
_HDL = {  # HDL cholesterol, mmol/L
    "male":   {"20s": 1.30, "30s": 1.25, "40s": 1.20, "50s": 1.20, "60s": 1.25, "70s": 1.30, "80+": 1.30},
    "female": {"20s": 1.60, "30s": 1.60, "40s": 1.55, "50s": 1.55, "60s": 1.60, "70s": 1.60, "80+": 1.55},
}

# Field metadata for clean labelling in the UI (kept local to avoid coupling).
_META = {
    "systolic_bp": ("Systolic blood pressure", "mmHg"),
    "total_chol":  ("Total cholesterol", "mmol/L"),
    "hdl":         ("HDL cholesterol", "mmol/L"),
    "chol_ratio":  ("Total : HDL ratio", "ratio"),
}

ESTIMABLE = set(_META.keys())

_SOURCE = ("typical population average for your age and sex "
           "(approximate, from adult health-survey data)")


def _bmi(inputs: dict) -> Optional[float]:
    try:
        h = float(inputs["height_cm"]) / 100.0
        w = float(inputs["weight_kg"])
        if h > 0:
            return w / (h * h)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def estimate_field(field_key: str, sex: str, age: float,
                   bmi: Optional[float] = None) -> tuple[Optional[float], str]:
    """Return (estimated_value, provenance_note) or (None, '') if unsupported."""
    sex = "female" if str(sex).lower().startswith("f") else "male"
    band = _band(age)

    if field_key == "systolic_bp":
        val = float(_SBP[sex][band])
        note = _SOURCE
        if bmi is not None:
            # Well-established direction: higher BMI -> higher SBP. Conservative,
            # bounded nudge of ~0.6 mmHg per BMI unit away from ~24, capped at ±8.
            adj = max(-8.0, min(8.0, (bmi - 24.0) * 0.6))
            if abs(adj) >= 1.0:
                val += adj
                note += "; lightly adjusted for your BMI"
        return round(val), note

    if field_key == "total_chol":
        return round(_TOTAL_CHOL[sex][band], 1), _SOURCE
    if field_key == "hdl":
        return round(_HDL[sex][band], 2), _SOURCE
    if field_key == "chol_ratio":
        ratio = _TOTAL_CHOL[sex][band] / _HDL[sex][band]
        return round(ratio, 1), _SOURCE + " (total ÷ HDL of typical values)"
    return None, ""


def apply_estimates(inputs: dict, estimate_keys) -> tuple[dict, list, list]:
    """
    Fill any requested estimable fields that are missing.

    Returns (filled_inputs, estimated_info, warnings):
      filled_inputs  : a COPY of inputs with estimated values added
      estimated_info : [{key,label,value,unit,note}] for the UI to show
      warnings       : list[str] (a single reduced-reliability note if anything
                       was estimated)
    """
    keys = set(estimate_keys or [])
    out = dict(inputs)
    info: list = []
    if not keys:
        return out, info, []

    sex = inputs.get("sex")
    age = inputs.get("age")
    if sex is None or age is None:
        return out, info, []  # need both to estimate anything
    try:
        age = float(age)
    except (TypeError, ValueError):
        return out, info, []

    bmi = _bmi(inputs)
    for key in keys:
        if key not in ESTIMABLE:
            continue
        # only estimate when the user hasn't supplied a real value
        existing = inputs.get(key)
        if existing is not None and existing != "":
            continue
        value, note = estimate_field(key, sex, age, bmi)
        if value is None:
            continue
        out[key] = value
        label, unit = _META[key]
        info.append({"key": key, "label": label, "value": value, "unit": unit, "note": note})

    warnings = []
    if info:
        labels = ", ".join(i["label"].lower() for i in info)
        warnings.append(
            f"This estimate uses a typical population value for: {labels}. "
            "Because at least one input was filled in for you, treat the result as "
            "a rough, population-typical figure rather than a personal one."
        )
    return out, info, warnings
