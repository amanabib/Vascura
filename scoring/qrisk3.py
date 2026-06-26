"""
scoring/qrisk3.py — QRISK3-2017 wrapper around the faithful engine.

Maps friendly questionnaire inputs to the ClinRisk engine, handles missing values
the QRISK way (substitute population averages), clamps to the calculator's input
ranges, and adds QRISK3's signature extra outputs: heart age and relative risk
vs a healthy person.

Engine input coding (0-indexed, matches qrisk3_engine.py):
  smoke_cat: 0 non, 1 ex, 2 light(<10/day), 3 moderate(10-19), 4 heavy(>=20)
  ethrisk:   1 White/not stated, 2 Indian, 3 Pakistani, 4 Bangladeshi,
             5 Other Asian, 6 Black Caribbean, 7 Black African, 8 Chinese, 9 Other
"""
from __future__ import annotations
import math
from .qrisk3_engine import cvd_female_raw, cvd_male_raw
from .common import ScoreResult, risk_to_score_and_band, leave_one_out, Factor

AGE_MIN, AGE_MAX = 25, 84
MODEL = "QRISK3"
MODEL_LABEL = "QRISK3 (UK, 2017)"

# Population means used both for centring (engine) and for missing-value substitution.
MEAN = {
    "female": {"rati": 3.476326465606690, "sbp": 123.130012512207030, "sbps5": 9.002537727355957},
    "male":   {"rati": 4.300998687744141, "sbp": 128.571578979492190, "sbps5": 8.756621360778809},
}
# Input ranges accepted by the official qrisk.org form; we clamp as a backstop.
CLAMP = {"rati": (1.0, 12.0), "sbp": (70.0, 210.0), "sbps5": (0.0, 30.0), "bmi": (18.0, 47.0)}

SMOKE_MAP = {"non": 0, "ex": 1, "light": 2, "moderate": 3, "heavy": 4}
ETHNICITY_MAP = {
    "white": 1, "indian": 2, "pakistani": 3, "bangladeshi": 4, "other_asian": 5,
    "black_caribbean": 6, "black_african": 7, "chinese": 8, "other": 9,
}


def _clamp(v, key):
    lo, hi = CLAMP[key]
    return max(lo, min(hi, v))


def _run_engine(sex, e):
    """e is the dict of engine kwargs. Returns 10-year risk percent."""
    if sex == "female":
        return cvd_female_raw(
            age=e["age"], b_AF=e["b_AF"], b_atypicalantipsy=e["b_atypicalantipsy"],
            b_corticosteroids=e["b_corticosteroids"], b_migraine=e["b_migraine"], b_ra=e["b_ra"],
            b_renal=e["b_renal"], b_semi=e["b_semi"], b_sle=e["b_sle"], b_treatedhyp=e["b_treatedhyp"],
            b_type1=e["b_type1"], b_type2=e["b_type2"], bmi=e["bmi"], ethrisk=e["ethrisk"],
            fh_cvd=e["fh_cvd"], rati=e["rati"], sbp=e["sbp"], sbps5=e["sbps5"],
            smoke_cat=e["smoke_cat"], surv=10, town=e["town"])
    return cvd_male_raw(
        age=e["age"], b_AF=e["b_AF"], b_atypicalantipsy=e["b_atypicalantipsy"],
        b_corticosteroids=e["b_corticosteroids"], b_impotence2=e["b_impotence2"],
        b_migraine=e["b_migraine"], b_ra=e["b_ra"], b_renal=e["b_renal"], b_semi=e["b_semi"],
        b_sle=e["b_sle"], b_treatedhyp=e["b_treatedhyp"], b_type1=e["b_type1"], b_type2=e["b_type2"],
        bmi=e["bmi"], ethrisk=e["ethrisk"], fh_cvd=e["fh_cvd"], rati=e["rati"], sbp=e["sbp"],
        sbps5=e["sbps5"], smoke_cat=e["smoke_cat"], surv=10, town=e["town"])


def _healthy_engine(sex, age, ethrisk):
    """A person of the same age/sex with ideal modifiable risk factors (JBS3 convention)."""
    return {
        "age": age, "b_AF": 0, "b_atypicalantipsy": 0, "b_corticosteroids": 0, "b_impotence2": 0,
        "b_migraine": 0, "b_ra": 0, "b_renal": 0, "b_semi": 0, "b_sle": 0, "b_treatedhyp": 0,
        "b_type1": 0, "b_type2": 0, "bmi": 25.0, "ethrisk": ethrisk, "fh_cvd": 0,
        "rati": 4.0, "sbp": 125.0, "sbps5": 0.0, "smoke_cat": 0, "town": 0.0,
    }


def _heart_age(sex, risk_percent, ethrisk_for_heartage=1):
    """Age at which a healthy person (ideal factors, White reference) has this risk."""
    lo, hi = AGE_MIN, AGE_MAX
    r_lo = _run_engine(sex, _healthy_engine(sex, lo, ethrisk_for_heartage))
    r_hi = _run_engine(sex, _healthy_engine(sex, hi, ethrisk_for_heartage))
    if risk_percent <= r_lo:
        return f"≤{AGE_MIN}"
    if risk_percent >= r_hi:
        return f"≥{AGE_MAX}"
    # bisection on integer-ish age
    for _ in range(40):
        mid = (lo + hi) / 2
        if _run_engine(sex, _healthy_engine(sex, mid, ethrisk_for_heartage)) < risk_percent:
            lo = mid
        else:
            hi = mid
    return int(round((lo + hi) / 2))


def score(inp: dict) -> ScoreResult:
    sex = inp["sex"]
    age = int(inp["age"])
    warnings, missing = [], []

    if not (AGE_MIN <= age <= AGE_MAX):
        return ScoreResult(
            model=MODEL, model_label=MODEL_LABEL, risk_percent=None, score_0_100=None,
            band=None, band_index=None, in_valid_age_range=False, age_min=AGE_MIN, age_max=AGE_MAX,
            clinical_note=(f"QRISK3 is only validated for ages {AGE_MIN}-{AGE_MAX}. "
                           f"At age {age} it cannot give a reliable estimate."),
            key_factors=[], warnings=[f"Age {age} is outside the validated range."])

    ethrisk = inp.get("ethrisk") or ETHNICITY_MAP.get(inp.get("ethnicity", "white"), 1)
    smoke = inp.get("smoke_cat")
    if smoke is None:
        smoke = SMOKE_MAP.get(inp.get("smoking", "non"), 0)

    # BMI from height/weight
    h_m = float(inp["height_cm"]) / 100.0
    bmi = float(inp["weight_kg"]) / (h_m * h_m)
    bmi = _clamp(bmi, "bmi")

    # Cholesterol ratio / SBP / SBP-SD: substitute mean if unknown (QRISK behaviour).
    rati = inp.get("chol_ratio")
    if rati in (None, "", "unknown"):
        rati = MEAN[sex]["rati"]; missing.append("cholesterol ratio")
    else:
        rati = _clamp(float(rati), "rati")
    sbp = inp.get("systolic_bp")
    if sbp in (None, "", "unknown"):
        sbp = MEAN[sex]["sbp"]; missing.append("systolic blood pressure")
    else:
        sbp = _clamp(float(sbp), "sbp")
    sbps5 = inp.get("sbp_sd")
    if sbps5 in (None, "", "unknown"):
        sbps5 = MEAN[sex]["sbps5"]
    else:
        sbps5 = _clamp(float(sbps5), "sbps5")

    diab = inp.get("diabetes", "none")
    e = {
        "age": age,
        "b_AF": int(bool(inp.get("af"))),
        "b_atypicalantipsy": int(bool(inp.get("atypical_antipsychotics"))),
        "b_corticosteroids": int(bool(inp.get("corticosteroids"))),
        "b_impotence2": int(bool(inp.get("erectile_dysfunction"))) if sex == "male" else 0,
        "b_migraine": int(bool(inp.get("migraine"))),
        "b_ra": int(bool(inp.get("rheumatoid_arthritis"))),
        "b_renal": int(bool(inp.get("ckd"))),
        "b_semi": int(bool(inp.get("severe_mental_illness"))),
        "b_sle": int(bool(inp.get("sle"))),
        "b_treatedhyp": int(bool(inp.get("bp_treatment"))),
        "b_type1": 1 if diab == "type1" else 0,
        "b_type2": 1 if diab == "type2" else 0,
        "bmi": bmi, "ethrisk": ethrisk, "fh_cvd": int(bool(inp.get("family_history"))),
        "rati": rati, "sbp": sbp, "sbps5": sbps5, "smoke_cat": smoke, "town": float(inp.get("townsend") or 0.0),
    }

    risk = _run_engine(sex, e)
    score_0_100, band, band_index = risk_to_score_and_band(risk)

    # Extra outputs: heart age + relative risk vs a healthy peer of same age/sex/ethnicity.
    healthy_same = _run_engine(sex, _healthy_engine(sex, age, ethrisk))
    rel_risk = round(risk / healthy_same, 1) if healthy_same > 0 else None
    heart_age = _heart_age(sex, risk)
    extras = {
        "heart_age": heart_age,
        "relative_risk": rel_risk,
        "healthy_reference_risk_percent": round(healthy_same, 1),
    }

    # Deterministic key factors (leave-one-out on engine inputs).
    sex_mean = MEAN[sex]
    factor_specs = [
        {"key": "smoke_cat", "neutral": 0, "label": "Smoking"},
        {"key": "rati", "neutral": sex_mean["rati"], "label": "Cholesterol ratio (total:HDL)"},
        {"key": "sbp", "neutral": sex_mean["sbp"], "label": "Systolic blood pressure"},
        {"key": "bmi", "neutral": 25.0, "label": "Body mass index"},
        {"key": "b_treatedhyp", "neutral": 0, "label": "On blood-pressure treatment"},
        {"key": "b_type1", "neutral": 0, "label": "Type 1 diabetes"},
        {"key": "b_type2", "neutral": 0, "label": "Type 2 diabetes"},
        {"key": "fh_cvd", "neutral": 0, "label": "Family history of CVD"},
        {"key": "b_AF", "neutral": 0, "label": "Atrial fibrillation"},
        {"key": "b_renal", "neutral": 0, "label": "Chronic kidney disease"},
        {"key": "b_ra", "neutral": 0, "label": "Rheumatoid arthritis"},
        {"key": "b_sle", "neutral": 0, "label": "Systemic lupus erythematosus"},
        {"key": "b_migraine", "neutral": 0, "label": "Migraines"},
        {"key": "b_semi", "neutral": 0, "label": "Severe mental illness"},
        {"key": "b_corticosteroids", "neutral": 0, "label": "Regular corticosteroids"},
        {"key": "b_atypicalantipsy", "neutral": 0, "label": "Atypical antipsychotics"},
        {"key": "b_impotence2", "neutral": 0, "label": "Erectile dysfunction"},
    ]
    factors = leave_one_out(lambda ee: _run_engine(sex, ee), e, factor_specs)
    # Age is the dominant non-modifiable driver: report it descriptively.
    factors.insert(0, Factor(label="Age", direction="raises",
                             delta_points=0.0, detail=f"Age {age} is the main fixed driver of this estimate."))

    note = ("NICE suggests discussing a statin once 10-year QRISK3 risk reaches about 10%. "
            f"Your estimate is {round(risk,1)}%. ")
    if missing:
        note += "Some inputs were missing and replaced with population averages, which lowers accuracy."

    return ScoreResult(
        model=MODEL, model_label=MODEL_LABEL, risk_percent=round(risk, 1),
        score_0_100=score_0_100, band=band, band_index=band_index, in_valid_age_range=True,
        age_min=AGE_MIN, age_max=AGE_MAX, clinical_note=note, key_factors=factors, extras=extras,
        missing_inputs=missing, warnings=warnings,
        inputs_used={"bmi": round(bmi, 1), "cholesterol_ratio": round(rati, 2),
                     "systolic_bp": round(sbp, 0), "ethnicity_code": ethrisk, "smoke_cat": smoke})
