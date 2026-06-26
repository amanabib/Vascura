"""
tests/test_scoring.py — verification that the scoring engines are faithful.

Run from the project root:
    python -m pytest -q
or without pytest installed:
    python tests/test_scoring.py

QRISK3 : checked against 48 official ClinRisk reference profiles (exact, to rounding).
ASCVD  : checked against 4 canonical reference values from the CVrisk package docs.
SCORE2 : the published ESC material ships no machine-readable reference table, so we
         assert internal consistency, correct age-band routing, and monotonicity, and
         we print a few values you should confirm against the ESC HeartScore tool.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring.qrisk3_engine import cvd_female_raw, cvd_male_raw  # noqa: E402
from scoring import qrisk3, score2, ascvd                        # noqa: E402
from scoring.ascvd import _risk_percent as ascvd_risk            # noqa: E402
import estimate as estimator                                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def test_qrisk3_matches_48_reference_profiles():
    refs = json.load(open(os.path.join(HERE, "qrisk3_reference.json")))
    worst = 0.0
    for r in refs:
        # Reference smoke_cat is 1-indexed (1 = non-smoker); the engine is 0-indexed.
        sc = int(r["smoke_cat"]) - 1
        bmi = r["weight"] / ((r["height"] / 100.0) ** 2)  # engine recomputes BMI from wt/ht
        common = dict(age=int(r["age"]), b_AF=r["b_AF"], b_atypicalantipsy=r["b_atypicalantipsy"],
                      b_corticosteroids=r["b_corticosteroids"], b_migraine=r["b_migraine"],
                      b_ra=r["b_ra"], b_renal=r["b_renal"], b_semi=r["b_semi"], b_sle=r["b_sle"],
                      b_treatedhyp=r["b_treatedhyp"], b_type1=r["b_type1"], b_type2=r["b_type2"],
                      bmi=bmi, ethrisk=int(r["ethrisk"]), fh_cvd=r["fh_cvd"], rati=r["rati"],
                      sbp=r["sbp"], sbps5=r["sbps5"], smoke_cat=sc, surv=10, town=r["town"])
        got = cvd_female_raw(**common) if r["gender"] == 1.0 \
            else cvd_male_raw(b_impotence2=r["b_impotence2"], **common)
        worst = max(worst, abs(got - r["QRISK_C_algorithm_score"]))
    assert worst < 0.05, f"QRISK3 worst diff {worst:.4f}pp exceeds tolerance"
    return worst


def test_ascvd_matches_reference_values():
    # age 55, TC 213 mg/dL, HDL 50, SBP 140 untreated, non-smoker, non-diabetic
    cases = [("aa", "male", 7.95), ("aa", "female", 5.08),
             ("white", "female", 2.76), ("white", "male", 7.01)]
    worst = 0.0
    for race, sex, exp in cases:
        got = ascvd_risk(sex, 55, race, 213, 50, 140, 0, 0, 0)
        worst = max(worst, abs(got - exp))
    assert worst < 0.1, f"ASCVD worst diff {worst:.4f}pp exceeds tolerance"
    return worst


def test_score2_age_band_routing():
    # 69 -> SCORE2, 70 -> SCORE2-OP
    r69 = score2.score(dict(sex="male", age=69, smoker=0, systolic_bp=140, total_chol=6, hdl=1.3))
    r70 = score2.score(dict(sex="male", age=70, smoker=0, systolic_bp=140, total_chol=6, hdl=1.3))
    assert r69.extras["variant"] == "SCORE2"
    assert r70.extras["variant"] == "SCORE2-OP"
    # out of range handled
    assert score2.score(dict(sex="male", age=39, smoker=0, systolic_bp=120,
                             total_chol=5, hdl=1.3)).in_valid_age_range is False
    assert score2.score(dict(sex="male", age=90, smoker=0, systolic_bp=120,
                             total_chol=5, hdl=1.3)).in_valid_age_range is False


def test_score2_monotonic_in_risk_factors():
    base = dict(sex="male", age=55, smoker=0, systolic_bp=120, total_chol=5.0, hdl=1.5)
    r0 = score2.score(base).risk_percent
    r_smoke = score2.score({**base, "smoker": 1}).risk_percent
    r_bp = score2.score({**base, "systolic_bp": 160}).risk_percent
    r_chol = score2.score({**base, "total_chol": 7.5}).risk_percent
    assert r_smoke > r0 and r_bp > r0 and r_chol > r0, "risk should rise with each adverse factor"


def test_bands_and_score_consistency():
    # score_0_100 equals rounded percentage; band index in range
    for inp in [dict(sex="female", age=60, ethnicity="white", smoking="non", height_cm=165,
                     weight_kg=70, chol_ratio=4.0, systolic_bp=130, diabetes="none")]:
        res = qrisk3.score(inp)
        assert res.score_0_100 == round(res.risk_percent)
        assert 0 <= res.band_index <= 5


def test_estimate_fills_only_requested_missing_fields():
    # Female 62: request cholesterol estimates; supplied SBP must be left untouched.
    inp = {"sex": "female", "age": 62, "systolic_bp": 135}
    filled, info, warns = estimator.apply_estimates(inp, ["total_chol", "hdl"])
    keys = {i["key"] for i in info}
    assert keys == {"total_chol", "hdl"}          # both filled
    assert "total_chol" in filled and "hdl" in filled
    assert filled["systolic_bp"] == 135            # real value preserved
    assert warns and "rough" in warns[0].lower()   # reliability flagged


def test_estimate_does_not_override_supplied_values():
    inp = {"sex": "male", "age": 50, "total_chol": 4.0}
    filled, info, _ = estimator.apply_estimates(inp, ["total_chol"])
    assert info == []                  # nothing estimated, value was present
    assert filled["total_chol"] == 4.0


def test_estimate_sbp_bmi_adjustment_direction():
    # Higher BMI should not lower the estimated systolic BP.
    base = {"sex": "male", "age": 55, "height_cm": 175, "weight_kg": 70}   # BMI ~22.9
    heavy = {"sex": "male", "age": 55, "height_cm": 175, "weight_kg": 100}  # BMI ~32.7
    lo, _, _ = estimator.apply_estimates(base, ["systolic_bp"])
    hi, _, _ = estimator.apply_estimates(heavy, ["systolic_bp"])
    assert hi["systolic_bp"] >= lo["systolic_bp"]


if __name__ == "__main__":
    qw = test_qrisk3_matches_48_reference_profiles()
    aw = test_ascvd_matches_reference_values()
    test_score2_age_band_routing()
    test_score2_monotonic_in_risk_factors()
    test_bands_and_score_consistency()
    test_estimate_fills_only_requested_missing_fields()
    test_estimate_does_not_override_supplied_values()
    test_estimate_sbp_bmi_adjustment_direction()
    print(f"QRISK3: 48/48 reference profiles match (worst {qw:.4f}pp)")
    print(f"ASCVD : 4/4 reference values match (worst {aw:.4f}pp)")
    print("SCORE2: age-band routing + monotonicity OK")
    print("ESTIM.: estimation fill / no-override / BMI direction OK")
    print()
    # Spot-check values to confirm against ESC HeartScore (https://www.heartscore.org/):
    for sex, age, sm, sbp, tc, hdl in [("male", 50, 0, 140, 6.3, 1.4),
                                       ("female", 60, 1, 150, 6.0, 1.3),
                                       ("male", 75, 0, 145, 5.5, 1.4)]:
        r = score2.score(dict(sex=sex, age=age, smoker=sm, systolic_bp=sbp, total_chol=tc, hdl=hdl))
        print(f"  SCORE2 spot-check {sex} age {age}: {r.risk_percent}% ({r.extras['variant']}) -> confirm on HeartScore")
    print("\nAll scoring tests passed.")
