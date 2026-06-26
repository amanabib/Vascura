"""
scoring/score2.py — SCORE2 and SCORE2-OP (European Society of Cardiology, 2021).

SCORE2 estimates 10-year risk of fatal AND non-fatal cardiovascular disease.
  * SCORE2     : ages 40-69
  * SCORE2-OP  : ages 70-89 ("older persons")

The coefficients below are the published ESC-2021 algorithm (SCORE2 Working Group
& ESC Cardiovascular Risk Collaboration, European Heart Journal 2021;42:2439-2454,
Updated Supplementary Material p.9). They are transcribed verbatim from the
open-source, peer-reviewed `RiskScorescvd` R package, which implements that same
published formula.

VERIFICATION NOTE
-----------------
Unlike QRISK3 (which ships 48 numeric reference vectors we check against), the
published SCORE2 material does not include a machine-readable reference table, so
this implementation is verified by spot-checking against the official ESC tools:
  * https://www.heartscore.org/  (ESC HeartScore)
  * https://u-prevent.com/calculators/score2   (SCORE2 calculator)
tests/test_scoring.py contains internal-consistency and monotonicity checks plus
documented spot-check values; users should confirm a few profiles against the
calculators above before relying on output.

DIABETES
--------
SCORE2 is NOT intended for, or validated in, people with diabetes — a dedicated
model (SCORE2-Diabetes) exists for them. The diabetes coefficient only existed in
the modelling for recalibration; for the target population it is always 0. We
therefore fix diabetes = 0 and do not collect it.

UNITS: cholesterol in mmol/L (UK standard). Region: UK is a LOW-risk region.
"""
from __future__ import annotations
import math
from .common import ScoreResult, risk_to_score_and_band, leave_one_out, Factor

MODEL = "SCORE2"
MODEL_LABEL = "SCORE2 / SCORE2-OP (Europe, ESC 2021)"
AGE_MIN, AGE_MAX = 40, 89          # SCORE2 40-69, SCORE2-OP 70-89
OP_THRESHOLD = 70

# Region recalibration scales: (scale1, scale2) keyed by (region, is_op, sex).
SCALES = {
    # --- under 70 (SCORE2) ---
    ("Low", False, "male"):       (-0.5699, 0.7476),
    ("Low", False, "female"):     (-0.7380, 0.7019),
    ("Moderate", False, "male"):  (-0.1565, 0.8009),
    ("Moderate", False, "female"):(-0.3143, 0.7701),
    ("High", False, "male"):      ( 0.3207, 0.9360),
    ("High", False, "female"):    ( 0.5710, 0.9369),
    ("Very high", False, "male"): ( 0.5836, 0.8294),
    ("Very high", False, "female"):(0.9412, 0.8329),
    # --- 70 and over (SCORE2-OP) ---
    ("Low", True, "male"):        (-0.34, 1.19),
    ("Low", True, "female"):      (-0.52, 1.01),
    ("Moderate", True, "male"):   ( 0.01, 1.25),
    ("Moderate", True, "female"): (-0.10, 1.10),
    ("High", True, "male"):       ( 0.08, 1.15),
    ("High", True, "female"):     ( 0.38, 1.09),
    ("Very high", True, "male"):  ( 0.05, 0.70),
    ("Very high", True, "female"):( 0.38, 0.69),
}


def _lp_under70(sex, age, smoker, sbp, chol, hdl, diabetes):
    """SCORE2 linear predictor (ages 40-69)."""
    a = (age - 60) / 5
    if sex == "male":
        return (0.3742 * a + 0.6012 * smoker + 0.2777 * (sbp - 120) / 20
                + 0.6457 * diabetes + 0.1458 * (chol - 6)
                + (-0.2698) * (hdl - 1.3) / 0.5
                + (-0.0755) * a * smoker
                + (-0.0255) * a * (sbp - 120) / 20
                + (-0.0281) * a * (chol - 6)
                + 0.0426 * a * (hdl - 1.3) / 0.5
                + (-0.0983) * a * diabetes)
    return (0.4648 * a + 0.7744 * smoker + 0.3131 * (sbp - 120) / 20
            + 0.8096 * diabetes + 0.1002 * (chol - 6)
            + (-0.2606) * (hdl - 1.3) / 0.5
            + (-0.1088) * a * smoker
            + (-0.0277) * a * (sbp - 120) / 20
            + (-0.0226) * a * (chol - 6)
            + 0.0613 * a * (hdl - 1.3) / 0.5
            + (-0.1272) * a * diabetes)


def _lp_op(sex, age, smoker, sbp, chol, hdl, diabetes):
    """SCORE2-OP linear predictor (ages 70-89)."""
    a = age - 73
    if sex == "male":
        return (0.0634 * a + 0.4245 * diabetes + 0.3524 * smoker
                + 0.0094 * (sbp - 150) + 0.0850 * (chol - 6)
                + (-0.3564) * (hdl - 1.4)
                + (-0.0174) * a * diabetes + (-0.0247) * a * smoker
                + (-0.0005) * a * (sbp - 150) + 0.0073 * a * (chol - 6)
                + 0.0091 * a * (hdl - 1.4))
    return (0.0789 * a + 0.6010 * diabetes + 0.4921 * smoker
            + 0.0102 * (sbp - 150) + 0.0605 * (chol - 6)
            + (-0.3040) * (hdl - 1.4)
            + (-0.0107) * a * diabetes + (-0.0255) * a * smoker
            + (-0.0004) * a * (sbp - 150) + (-0.0009) * a * (chol - 6)
            + 0.0154 * a * (hdl - 1.4))


# Baseline survival and OP exp-offset, per ESC supplement.
BASELINE = {  # (is_op, sex) -> (baseline_survival, op_offset)
    (False, "male"):   (0.9605, 0.0),
    (False, "female"): (0.9776, 0.0),
    (True, "male"):    (0.7576, 0.0929),
    (True, "female"):  (0.8082, 0.2290),
}


def _risk_percent(sex, age, smoker, sbp, chol, hdl, region, diabetes=0):
    is_op = age >= OP_THRESHOLD
    lp = _lp_op(sex, age, smoker, sbp, chol, hdl, diabetes) if is_op \
        else _lp_under70(sex, age, smoker, sbp, chol, hdl, diabetes)
    base, offset = BASELINE[(is_op, sex)]
    uncalibrated = 1 - base ** math.exp(lp - offset)
    scale1, scale2 = SCALES[(region, is_op, sex)]
    calibrated = 1 - math.exp(-math.exp(scale1 + scale2 * math.log(-math.log(1 - uncalibrated))))
    return calibrated * 100.0


def _clinical_note(age, risk):
    """SCORE2 uses AGE-SPECIFIC thresholds for what counts as low/moderate/high."""
    if age < 50:
        lo, hi = 2.5, 7.5
    elif age <= 69:
        lo, hi = 5.0, 10.0
    else:
        lo, hi = 7.5, 15.0
    if risk < lo:
        cat = "low"
    elif risk < hi:
        cat = "moderate"
    else:
        cat = "high"
    return (f"ESC reads SCORE2 against age-specific thresholds. For your age band the "
            f"cut-offs are {lo}% and {hi}%, so {round(risk,1)}% sits in the ESC '{cat}' "
            f"range. ESC guidance is to consider risk-factor treatment from the upper "
            f"threshold, individualised to the person.")


def score(inp: dict) -> ScoreResult:
    sex = inp["sex"]
    age = int(inp["age"])
    region = inp.get("region", "Low")          # UK = Low-risk region
    warnings, missing = [], []

    if not (AGE_MIN <= age <= AGE_MAX):
        return ScoreResult(
            model=MODEL, model_label=MODEL_LABEL, risk_percent=None, score_0_100=None,
            band=None, band_index=None, in_valid_age_range=False, age_min=AGE_MIN, age_max=AGE_MAX,
            clinical_note=(f"SCORE2 is validated for ages {AGE_MIN}-{AGE_MAX} "
                           f"(SCORE2 to 69, SCORE2-OP from 70). At age {age} it cannot give a "
                           f"reliable estimate."),
            key_factors=[], warnings=[f"Age {age} is outside the validated range."])

    smoker = 1 if (inp.get("smoker") in (1, True, "yes")
                   or inp.get("smoking") in ("light", "moderate", "heavy", "current")) else 0
    sbp = float(inp["systolic_bp"])
    chol = float(inp["total_chol"])            # mmol/L
    hdl = float(inp["hdl"])                     # mmol/L

    risk = _risk_percent(sex, age, smoker, sbp, chol, hdl, region, diabetes=0)
    score_0_100, band, band_index = risk_to_score_and_band(risk)

    # Deterministic key factors via leave-one-out on the model's own inputs.
    base = {"sex": sex, "age": age, "smoker": smoker, "sbp": sbp,
            "chol": chol, "hdl": hdl, "region": region}

    def fn(d):
        return _risk_percent(d["sex"], d["age"], d["smoker"], d["sbp"],
                             d["chol"], d["hdl"], d["region"], diabetes=0)

    specs = [
        {"key": "smoker", "neutral": 0, "label": "Smoking"},
        {"key": "sbp", "neutral": 120.0, "label": "Systolic blood pressure"},
        {"key": "chol", "neutral": 6.0, "label": "Total cholesterol"},
        {"key": "hdl", "neutral": 1.3 if age < OP_THRESHOLD else 1.4, "label": "HDL cholesterol"},
    ]
    factors = leave_one_out(fn, base, specs)
    factors.insert(0, Factor(label="Age", direction="raises", delta_points=0.0,
                             detail=f"Age {age} is the main fixed driver of this estimate."))

    return ScoreResult(
        model=MODEL, model_label=MODEL_LABEL, risk_percent=round(risk, 1),
        score_0_100=score_0_100, band=band, band_index=band_index, in_valid_age_range=True,
        age_min=AGE_MIN, age_max=AGE_MAX, clinical_note=_clinical_note(age, risk),
        key_factors=factors, missing_inputs=missing, warnings=warnings,
        extras={"variant": "SCORE2-OP" if age >= OP_THRESHOLD else "SCORE2",
                "risk_region": region},
        inputs_used={"systolic_bp": round(sbp, 0), "total_chol_mmol_l": round(chol, 2),
                     "hdl_mmol_l": round(hdl, 2), "smoker": smoker, "region": region})
