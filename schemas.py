"""
schemas.py — the single source of truth for the whole questionnaire.

The frontend renders entirely from what /api/models returns, and the backend
validates against the same definitions. To add a field you edit it here once.

Each model defines:
  key, name, one_liner, age_min, age_max,
  bullets      : <=4 plain-language "what this is" points for the selection card
  sections[]   : ordered groups of fields that DRIVE the score
A field is:
  {key, label, type, ...}
  type "select" -> options:[{value,label}]
  type "number" -> min,max,step,unit,(optional) help
  type "boolean"-> rendered as a toggle/checkbox

SUPPLEMENTARY_SECTIONS are shared across all models, collapsed by default, and are
explicitly marked affects_score=False. They never touch the maths — they are only
passed to the Claude advice layer to make its guidance more specific. This is also
where manually-entered wearable data (e.g. Garmin) lives.
"""
from __future__ import annotations
import copy

# ---- reusable field fragments -------------------------------------------------
SEX = {"key": "sex", "label": "Sex at birth", "type": "select",
       "help": "Risk models are calibrated separately for male and female physiology.",
       "options": [{"value": "male", "label": "Male"}, {"value": "female", "label": "Female"}]}

SMOKING_CATEGORICAL = {  # QRISK3 distinguishes intensity
    "key": "smoking", "label": "Smoking status", "type": "select",
    "options": [
        {"value": "non", "label": "Non-smoker"},
        {"value": "ex", "label": "Ex-smoker"},
        {"value": "light", "label": "Light smoker (under 10/day)"},
        {"value": "moderate", "label": "Moderate smoker (10-19/day)"},
        {"value": "heavy", "label": "Heavy smoker (20+/day)"},
    ]}

SMOKER_BINARY = {  # SCORE2 / ASCVD use yes/no
    "key": "smoker", "label": "Current smoker?", "type": "select",
    "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes"}]}

SYSTOLIC = {"key": "systolic_bp", "label": "Systolic blood pressure", "type": "number",
            "min": 70, "max": 210, "step": 1, "unit": "mmHg", "estimable": True,
            "help": "The upper (first) number from a blood-pressure reading."}

BP_TREATMENT = {"key": "bp_treatment", "label": "On blood-pressure medication?", "type": "select",
                "options": [{"value": "no", "label": "No"}, {"value": "yes", "label": "Yes"}]}

TOTAL_CHOL = {"key": "total_chol", "label": "Total cholesterol", "type": "number",
              "min": 2.0, "max": 12.0, "step": 0.1, "unit": "mmol/L", "estimable": True,
              "help": "From a standard lipid blood test (UK units)."}

HDL = {"key": "hdl", "label": "HDL ('good') cholesterol", "type": "number",
       "min": 0.5, "max": 3.5, "step": 0.1, "unit": "mmol/L", "estimable": True}

DIABETES_FULL = {"key": "diabetes", "label": "Diabetes", "type": "select",
                 "options": [{"value": "none", "label": "None"},
                             {"value": "type1", "label": "Type 1"},
                             {"value": "type2", "label": "Type 2"}]}

DIABETES_BINARY = {"key": "diabetes", "label": "Diabetes?", "type": "select",
                   "options": [{"value": "none", "label": "No"}, {"value": "yes", "label": "Yes"}]}

ETHNICITY = {"key": "ethnicity", "label": "Ethnicity", "type": "select",
             "help": "QRISK3 adjusts for ethnicity using UK cohort data.",
             "options": [
                 {"value": "white", "label": "White or not stated"},
                 {"value": "indian", "label": "Indian"},
                 {"value": "pakistani", "label": "Pakistani"},
                 {"value": "bangladeshi", "label": "Bangladeshi"},
                 {"value": "other_asian", "label": "Other Asian"},
                 {"value": "black_caribbean", "label": "Black Caribbean"},
                 {"value": "black_african", "label": "Black African"},
                 {"value": "chinese", "label": "Chinese"},
                 {"value": "other", "label": "Other ethnic group"},
             ]}

RACE_ASCVD = {"key": "race", "label": "Race", "type": "select",
              "help": "The Pooled Cohort Equations were derived for White and "
                      "African-American populations; other groups use the White equation.",
              "options": [
                  {"value": "white", "label": "White / other"},
                  {"value": "aa", "label": "African-American"},
              ]}

HEIGHT = {"key": "height_cm", "label": "Height", "type": "number",
          "min": 130, "max": 210, "step": 1, "unit": "cm"}
WEIGHT = {"key": "weight_kg", "label": "Weight", "type": "number",
          "min": 35, "max": 200, "step": 1, "unit": "kg"}

CHOL_RATIO = {"key": "chol_ratio", "label": "Total : HDL cholesterol ratio", "type": "number",
              "min": 1.0, "max": 12.0, "step": 0.1, "unit": "ratio", "optional": True, "estimable": True,
              "help": "Total cholesterol divided by HDL. Don't know it? Tick \u201cEstimate this\u201d "
                      "to use a typical value for your age and sex."}

# QRISK3 medical-history booleans (these DO affect the QRISK3 score).
QRISK_CONDITIONS = [
    {"key": "family_history", "label": "Angina or heart attack in a first-degree relative under 60", "type": "boolean"},
    {"key": "af", "label": "Atrial fibrillation", "type": "boolean"},
    {"key": "ckd", "label": "Chronic kidney disease (stage 3, 4 or 5)", "type": "boolean"},
    {"key": "bp_treatment", "label": "On blood-pressure treatment", "type": "boolean"},
    {"key": "rheumatoid_arthritis", "label": "Rheumatoid arthritis", "type": "boolean"},
    {"key": "sle", "label": "Systemic lupus erythematosus (SLE)", "type": "boolean"},
    {"key": "migraine", "label": "Migraines", "type": "boolean"},
    {"key": "severe_mental_illness", "label": "Severe mental illness", "type": "boolean"},
    {"key": "corticosteroids", "label": "On regular steroid tablets", "type": "boolean"},
    {"key": "atypical_antipsychotics", "label": "On atypical antipsychotic medication", "type": "boolean"},
    {"key": "erectile_dysfunction", "label": "Erectile dysfunction", "type": "boolean", "sex": "male"},
]

# ---- per-model schemas --------------------------------------------------------
MODELS = {
    "qrisk3": {
        "key": "qrisk3",
        "name": "QRISK3",
        "one_liner": "The UK's NHS model for 10-year heart-attack and stroke risk.",
        "age_min": 25, "age_max": 84,
        "bullets": [
            "Used across the NHS and recommended by NICE",
            "Tuned to UK populations, including ethnicity and deprivation",
            "Accounts for many conditions (diabetes, kidney disease, lupus and more)",
            "Best fit if you live in the UK",
        ],
        "cohort_citation": "Derived from the QResearch primary-care database of several "
                           "million UK patients. Hippisley-Cox J, et al. BMJ 2017;357:j2099.",
        "cohort_source_url": "https://qrisk.org",
        "sections": [
            {"title": "About you", "fields": [SEX,
                {"key": "age", "label": "Age", "type": "number", "min": 25, "max": 84, "step": 1, "unit": "years"},
                ETHNICITY]},
            {"title": "Measurements", "fields": [HEIGHT, WEIGHT, SYSTOLIC, CHOL_RATIO]},
            {"title": "Smoking & diabetes", "fields": [SMOKING_CATEGORICAL, DIABETES_FULL]},
            {"title": "Medical history", "subtitle": "Tick any that apply.", "fields": QRISK_CONDITIONS},
        ],
    },
    "score2": {
        "key": "score2",
        "name": "SCORE2 / SCORE2-OP",
        "one_liner": "The European Society of Cardiology model for fatal and non-fatal CVD.",
        "age_min": 40, "age_max": 89,
        "bullets": [
            "Endorsed across Europe by the ESC (2021)",
            "Covers ages 40 to 89 (SCORE2-OP handles 70+)",
            "Uses age-specific thresholds for what counts as high risk",
            "Calibrated to a country's risk region (UK = low)",
        ],
        "cohort_citation": "Derived from 45 European cohorts (~677,000 participants) and "
                           "recalibrated by region. SCORE2 working group & ESC CRC, "
                           "Eur Heart J 2021;42:2439-2454.",
        "cohort_source_url": "https://www.escardio.org/Education/Practice-Tools/CVD-prevention-toolbox/SCORE-Risk-Charts",
        "sections": [
            {"title": "About you", "fields": [SEX,
                {"key": "age", "label": "Age", "type": "number", "min": 40, "max": 89, "step": 1, "unit": "years"}]},
            {"title": "Measurements", "fields": [SYSTOLIC, TOTAL_CHOL, HDL]},
            {"title": "Smoking", "fields": [SMOKER_BINARY]},
        ],
    },
    "ascvd": {
        "key": "ascvd",
        "name": "ASCVD (Pooled Cohort)",
        "one_liner": "The US ACC/AHA model for 10-year atherosclerotic CVD risk.",
        "age_min": 40, "age_max": 79,
        "bullets": [
            "The standard US risk calculator (ACC/AHA, 2013)",
            "Covers ages 40 to 79",
            "Estimates heart attack and stroke risk",
            "Best fit if you are in the United States",
        ],
        "cohort_citation": "Pooled from several US community cohorts (ARIC, CHS, CARDIA and "
                           "the Framingham studies). Goff DC, et al. Circulation 2014;129(25 Suppl 2):S49-S73.",
        "cohort_source_url": "https://www.ahajournals.org/doi/10.1161/01.cir.0000437741.48606.98",
        "sections": [
            {"title": "About you", "fields": [SEX,
                {"key": "age", "label": "Age", "type": "number", "min": 40, "max": 79, "step": 1, "unit": "years"},
                RACE_ASCVD]},
            {"title": "Measurements", "fields": [TOTAL_CHOL, HDL, SYSTOLIC, BP_TREATMENT]},
            {"title": "Smoking & diabetes", "fields": [SMOKER_BINARY, DIABETES_BINARY]},
        ],
    },
}

# ---- supplementary (NEVER affects the score) ---------------------------------
SUPPLEMENTARY_SECTIONS = [
    {
        "id": "advanced",
        "title": "Advanced & home measurements",
        "affects_score": False,
        "note": "Optional. These do not change your score — they help the AI tailor its advice.",
        "fields": [
            {"key": "resting_hr", "label": "Resting heart rate", "type": "number",
             "min": 30, "max": 120, "step": 1, "unit": "bpm", "optional": True,
             "help": "From a wearable (e.g. Garmin) or a one-minute count at rest."},
            {"key": "vo2max", "label": "Estimated VO2 max", "type": "number",
             "min": 15, "max": 80, "step": 1, "unit": "ml/kg/min", "optional": True,
             "help": "Many watches estimate this; a strong marker of fitness."},
            {"key": "waist_cm", "label": "Waist circumference", "type": "number",
             "min": 50, "max": 160, "step": 1, "unit": "cm", "optional": True},
            {"key": "hba1c", "label": "HbA1c", "type": "number",
             "min": 20, "max": 130, "step": 1, "unit": "mmol/mol", "optional": True,
             "help": "A blood marker of average glucose, if you know it."},
        ],
    },
    {
        "id": "lifestyle",
        "title": "Lifestyle",
        "affects_score": False,
        "note": "Optional. Context for the AI advice only — these do not change your score.",
        "fields": [
            {"key": "exercise_mins", "label": "Moderate-vigorous exercise per week", "type": "number",
             "min": 0, "max": 1500, "step": 15, "unit": "minutes", "optional": True},
            {"key": "steps", "label": "Typical daily steps", "type": "number",
             "min": 0, "max": 40000, "step": 500, "unit": "steps", "optional": True},
            {"key": "alcohol_units", "label": "Alcohol per week", "type": "number",
             "min": 0, "max": 100, "step": 1, "unit": "UK units", "optional": True},
            {"key": "fruit_veg", "label": "Fruit & veg servings per day", "type": "number",
             "min": 0, "max": 15, "step": 1, "unit": "servings", "optional": True},
            {"key": "sleep_hours", "label": "Average sleep", "type": "number",
             "min": 3, "max": 12, "step": 0.5, "unit": "hours/night", "optional": True},
            {"key": "stress", "label": "Typical stress level", "type": "select", "optional": True,
             "options": [{"value": "", "label": "Prefer not to say"},
                         {"value": "low", "label": "Low"},
                         {"value": "moderate", "label": "Moderate"},
                         {"value": "high", "label": "High"}]},
        ],
    },
]


def model_list():
    """Lightweight metadata for the selection screen (no field detail)."""
    return [{"key": m["key"], "name": m["name"], "one_liner": m["one_liner"],
             "age_min": m["age_min"], "age_max": m["age_max"], "bullets": m["bullets"]}
            for m in MODELS.values()]


def model_schema(key: str):
    """Full schema for one model, plus the shared supplementary sections."""
    m = MODELS.get(key)
    if not m:
        return None
    out = copy.deepcopy(m)
    out["supplementary"] = copy.deepcopy(SUPPLEMENTARY_SECTIONS)
    return out


def core_field_keys(key: str):
    """Set of keys that legitimately feed the named model's score (for filtering)."""
    m = MODELS.get(key)
    keys = set()
    if not m:
        return keys
    for sec in m["sections"]:
        for f in sec["fields"]:
            keys.add(f["key"])
    return keys
