"""
scoring/ascvd.py — ACC/AHA 2013 Pooled Cohort Equations (ASCVD).

Estimates 10-year risk of a first hard atherosclerotic cardiovascular disease
event (non-fatal MI, CHD death, or fatal/non-fatal stroke). US model, ages 40-79.

Coefficients live in ascvd_pooled_coef.json, exported verbatim from the
peer-reviewed open-source `CVrisk` R package (which implements Goff et al.,
2013 ACC/AHA Guideline on the Assessment of Cardiovascular Risk, Circulation
2014;129(25 Suppl 2):S49-S73). There are four coefficient sets:
white/African-American x male/female. People of other/unspecified race are scored
with the white coefficients, the convention the guideline and CVrisk both use.

VERIFICATION: tests/test_scoring.py checks four canonical reference values
reproduced from CVrisk's own documented examples (worst diff < 0.1 percentage
points). UNITS: cholesterol must be mg/dL — we convert from mmol/L (UK) by the
standard factor 38.67.
"""
from __future__ import annotations
import json
import math
import pathlib
from .common import ScoreResult, risk_to_score_and_band, leave_one_out, Factor

MODEL = "ASCVD"
MODEL_LABEL = "ASCVD Pooled Cohort Equations (US, 2013)"
AGE_MIN, AGE_MAX = 40, 79
MMOL_L_TO_MG_DL = 38.67

_COEF = {(r["race"], r["gender"]): r
         for r in json.loads((pathlib.Path(__file__).parent / "ascvd_pooled_coef.json").read_text())}


def _risk_percent(sex, age, race, total_chol_mgdl, hdl_mgdl, sbp, bp_treated, smoker, diabetes):
    """Pooled Cohort Equation 10-year risk (%). race in {'white','aa'}."""
    c = _COEF[(race, sex)]
    ln_age = math.log(age)
    ln_tc = math.log(total_chol_mgdl)
    ln_hdl = math.log(hdl_mgdl)
    # Treated vs untreated SBP enter through separate coefficients; the unused one
    # is multiplied by ln(1)=0 (CVrisk encodes the inactive SBP as 1).
    sbp_treated = sbp if bp_treated else 1
    sbp_untreated = sbp if not bp_treated else 1
    ln_sbp_t = math.log(sbp_treated)
    ln_sbp_u = math.log(sbp_untreated)

    s = (c["ln_age"] * ln_age
         + c["ln_age_squared"] * ln_age ** 2
         + c["ln_totchol"] * ln_tc
         + c["ln_age_totchol"] * ln_age * ln_tc
         + c["ln_hdl"] * ln_hdl
         + c["ln_age_hdl"] * ln_age * ln_hdl
         + c["ln_treated_sbp"] * ln_sbp_t
         + c["ln_age_treated_sbp"] * ln_age * ln_sbp_t
         + c["ln_untreated_sbp"] * ln_sbp_u
         + c["ln_age_untreated_sbp"] * ln_age * ln_sbp_u
         + c["smoker"] * smoker
         + c["ln_age_smoker"] * ln_age * smoker
         + c["diabetes"] * diabetes)

    risk = (1 - c["baseline_survival"] ** math.exp(s - c["group_mean"])) * 100.0
    # CVrisk floors at 1% (very low estimates are not meaningfully distinguishable).
    return max(risk, 1.0)


def score(inp: dict) -> ScoreResult:
    sex = inp["sex"]
    age = int(inp["age"])
    warnings, missing = [], []

    if not (AGE_MIN <= age <= AGE_MAX):
        return ScoreResult(
            model=MODEL, model_label=MODEL_LABEL, risk_percent=None, score_0_100=None,
            band=None, band_index=None, in_valid_age_range=False, age_min=AGE_MIN, age_max=AGE_MAX,
            clinical_note=(f"The Pooled Cohort Equations are validated for ages {AGE_MIN}-{AGE_MAX}. "
                           f"At age {age} they cannot give a reliable estimate."),
            key_factors=[], warnings=[f"Age {age} is outside the validated range."])

    # Race: only white / African-American are modelled; map everything else to white.
    raw_race = (inp.get("race") or "white").lower()
    race = "aa" if raw_race in ("aa", "black", "african_american", "black_african",
                                "black_caribbean", "african-american") else "white"
    if race == "white" and raw_race not in ("white", "aa", "black"):
        warnings.append("The Pooled Cohort Equations only model White and African-American "
                        "ethnicity; other groups are scored with the White coefficients and may "
                        "be less accurate.")

    # Cholesterol: convert mmol/L -> mg/dL.
    chol_mgdl = float(inp["total_chol"]) * MMOL_L_TO_MG_DL
    hdl_mgdl = float(inp["hdl"]) * MMOL_L_TO_MG_DL
    sbp = float(inp["systolic_bp"])
    bp_treated = 1 if inp.get("bp_treatment") in (1, True, "yes") else 0
    smoker = 1 if (inp.get("smoker") in (1, True, "yes")
                   or inp.get("smoking") in ("light", "moderate", "heavy", "current")) else 0
    diab = inp.get("diabetes", "none")
    diabetes = 1 if diab in (1, True, "yes", "type1", "type2") else 0

    risk = _risk_percent(sex, age, race, chol_mgdl, hdl_mgdl, sbp, bp_treated, smoker, diabetes)
    score_0_100, band, band_index = risk_to_score_and_band(risk)

    # Deterministic key factors via leave-one-out.
    base = {"sex": sex, "age": age, "race": race, "chol": chol_mgdl, "hdl": hdl_mgdl,
            "sbp": sbp, "bp_treated": bp_treated, "smoker": smoker, "diabetes": diabetes}

    def fn(d):
        return _risk_percent(d["sex"], d["age"], d["race"], d["chol"], d["hdl"],
                             d["sbp"], d["bp_treated"], d["smoker"], d["diabetes"])

    specs = [
        {"key": "smoker", "neutral": 0, "label": "Smoking"},
        {"key": "diabetes", "neutral": 0, "label": "Diabetes"},
        {"key": "sbp", "neutral": 120.0, "label": "Systolic blood pressure"},
        {"key": "chol", "neutral": 170.0 * 1.0, "label": "Total cholesterol"},
        {"key": "hdl", "neutral": 50.0, "label": "HDL cholesterol"},
        {"key": "bp_treated", "neutral": 0, "label": "On blood-pressure treatment"},
    ]
    factors = leave_one_out(fn, base, specs)
    factors.insert(0, Factor(label="Age", direction="raises", delta_points=0.0,
                             detail=f"Age {age} is the main fixed driver of this estimate."))

    note = ("ACC/AHA reference points: below 5% is 'low', 5 to <7.5% 'borderline', "
            "7.5 to <20% 'intermediate', and 20% or above 'high'. A statin discussion "
            f"is generally recommended from 7.5%. Your estimate is {round(risk,1)}%.")

    return ScoreResult(
        model=MODEL, model_label=MODEL_LABEL, risk_percent=round(risk, 1),
        score_0_100=score_0_100, band=band, band_index=band_index, in_valid_age_range=True,
        age_min=AGE_MIN, age_max=AGE_MAX, clinical_note=note, key_factors=factors,
        missing_inputs=missing, warnings=warnings,
        extras={"race_used": race},
        inputs_used={"total_chol_mg_dl": round(chol_mgdl, 0), "hdl_mg_dl": round(hdl_mgdl, 0),
                     "systolic_bp": round(sbp, 0), "smoker": smoker, "diabetes": diabetes,
                     "race": race})
