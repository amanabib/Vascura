"""
advice.py — the Claude advice layer (the competition centrepiece).

The score is ALWAYS computed in scoring/ (plain Python). Claude never sees the
maths and is explicitly instructed to restate, never recompute, the number it is
handed. Claude's job is to:
  * explain what the (already-computed) result means in plain, non-alarming words,
  * say which factors are pushing the number up or down (we hand it the
    deterministic leave-one-out factors so it doesn't guess),
  * give 3-6 ranked, personalised, actionable recommendations, each with a short
    rationale and a reputable source (NHS, BHF, ESC, AHA, WHO),
  * return strict JSON so the frontend can render it.

Security: the API key is read from the environment on the SERVER. It is never sent
to or exposed in the browser. If ANTHROPIC_API_KEY is unset, or the call fails, we
fall back to a deterministic, source-backed static explanation so the app still
works end-to-end (and so it runs with zero cost for judging).
"""
from __future__ import annotations
import json
import os

# Model name can change over time — verify the current identifier at
# https://docs.claude.com/en/docs/about-claude/models . Sonnet balances quality and
# cost; Haiku (e.g. claude-haiku-4-5-20251001) is cheaper if you want lower spend.
ADVICE_MODEL = os.environ.get("ADVICE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 1400

SYSTEM_PROMPT = """You are a careful, warm health-education assistant inside a \
cardiovascular risk-awareness web app. You are NOT a doctor and you do NOT diagnose. \
Everything you write is general education to help someone understand a number that has \
already been calculated for them.

ABSOLUTE RULES
- The 10-year risk percentage, the 0-100 score, and the risk band have ALREADY been \
computed by validated, deterministic code and are given to you. RESTATE them exactly. \
NEVER recalculate, adjust, second-guess, or invent a different number or band.
- Use ONLY the risk band you are given. The six bands are: Low risk, Relatively low \
risk, Moderate risk, Relatively high risk, High risk, Very high risk.
- Be calm and non-alarming. No scare language, no catastrophising, no false reassurance. \
A higher number is information, not a verdict.
- This is education, not medical advice or diagnosis. Encourage the person to discuss \
results, and any changes to medication or lifestyle, with a GP or clinician. Do not tell \
them to start, stop, or change any specific medication.
- If inputs were missing and replaced with averages, mention briefly that this makes the \
estimate less precise.
- Recommendations must be practical, specific, and EASY TO ACT ON, ranked most-impactful \
first. Each needs a one-line plain rationale and a reputable source from this set: NHS, \
British Heart Foundation (BHF), European Society of Cardiology (ESC), American Heart \
Association (AHA), or WHO. Tie recommendations to THIS person's factors and any \
lifestyle/wearable details provided.
- Each recommendation MUST include a "topic" chosen from exactly this set: "nutrition", \
"exercise", "smoking", "blood_pressure", "sleep", "alcohol", "weight", "cholesterol", \
"diabetes", "general". The app uses this to attach verified help links.
- Do NOT include any URLs or links yourself — the application adds verified, reputable links \
based on each recommendation's topic. Writing your own links is not allowed.
- If the context states the person ALREADY MEETS physical-activity guidelines, do NOT include \
any recommendation to exercise more; briefly acknowledge their activity and use that slot for \
a different, useful recommendation.
- Never imply that a paid device, fitness tracker, or paid app is REQUIRED. If you mention \
tools at all, note that free options exist and that trackers are optional.
- Do not present the supplementary lifestyle or wearable details as if they changed the \
score; they did not. Use them only to make advice specific.

OUTPUT
Return ONLY a single JSON object, no markdown, no backticks, with exactly these keys:
{
  "interpretation": "1-2 sentences: what the score and band mean for this person, in plain language. Keep it short.",
  "key_factors": ["short phrases naming what is raising or lowering their risk"],
  "recommendations": [
    {"action": "imperative, specific", "why": "one-line rationale", "topic": "one of the allowed topics", "source": "NHS|BHF|ESC|AHA|WHO"}
  ],
  "closing_line": "one encouraging, non-alarming sentence pointing them to a clinician for anything personal."
}
Provide between 3 and 6 recommendations. Keep the whole response concise."""


# ---- curated, verified help links (the app attaches these; the LLM never writes URLs) ----
# Keyed by resource-set name. A country maps to one or more sets (see
# COUNTRY_RESOURCE_SETS): its own national bodies first, then WHO to supplement or
# substitute. Anything still missing falls back to the UK (NHS/BHF) set, which is
# high-quality and freely accessible worldwide.
RESOURCES = {
    "uk": {
        "nutrition": [{"label": "NHS Eatwell Guide", "url": "https://www.nhs.uk/live-well/eat-well/the-eatwell-guide/"},
                      {"label": "BHF healthy recipe finder", "url": "https://www.bhf.org.uk/informationsupport/support/healthy-living/healthy-eating/recipe-finder"}],
        "exercise": [{"label": "NHS exercise guidelines", "url": "https://www.nhs.uk/live-well/exercise/"},
                     {"label": "Free NHS Active 10 walking app", "url": "https://www.nhs.uk/active10/home"},
                     {"label": "NHS Couch to 5K", "url": "https://www.nhs.uk/live-well/exercise/running-and-aerobic-exercises/get-running-with-couch-to-5k/"}],
        "smoking": [{"label": "NHS Quit Smoking support", "url": "https://www.nhs.uk/better-health/quit-smoking/"}],
        "blood_pressure": [{"label": "NHS: how to lower blood pressure", "url": "https://www.nhs.uk/conditions/high-blood-pressure-hypertension/prevention/"},
                           {"label": "BHF blood pressure hub", "url": "https://www.bhf.org.uk/informationsupport/risk-factors/high-blood-pressure"}],
        "sleep": [{"label": "NHS: how to get to sleep", "url": "https://www.nhs.uk/live-well/sleep-and-tiredness/how-to-get-to-sleep/"}],
        "alcohol": [{"label": "NHS alcohol advice", "url": "https://www.nhs.uk/live-well/alcohol-advice/"}],
        "weight": [{"label": "NHS weight-loss plan", "url": "https://www.nhs.uk/better-health/lose-weight/"}],
        "cholesterol": [{"label": "NHS high cholesterol", "url": "https://www.nhs.uk/conditions/high-cholesterol/"},
                        {"label": "HEART UK", "url": "https://www.heartuk.org.uk/"}],
        "diabetes": [{"label": "NHS type 2 diabetes", "url": "https://www.nhs.uk/conditions/type-2-diabetes/"}],
        "general": [{"label": "NHS Health Check", "url": "https://www.nhs.uk/conditions/nhs-health-check/"}],
    },
    "us": {
        "nutrition": [{"label": "USDA MyPlate", "url": "https://www.myplate.gov/"},
                      {"label": "AHA healthy recipes", "url": "https://recipes.heart.org/"}],
        "exercise": [{"label": "AHA fitness basics", "url": "https://www.heart.org/en/healthy-living/fitness/fitness-basics"}],
        "smoking": [{"label": "Smokefree.gov quit support", "url": "https://smokefree.gov/"}],
        "blood_pressure": [{"label": "AHA: managing blood pressure", "url": "https://www.heart.org/en/health-topics/high-blood-pressure"}],
        "sleep": [{"label": "AHA: sleep & heart health", "url": "https://www.heart.org/en/healthy-living/healthy-lifestyle/sleep"}],
        "alcohol": [{"label": "AHA: alcohol & your heart", "url": "https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/nutrition-basics/alcohol-and-heart-health"}],
        "weight": [{"label": "AHA: losing weight", "url": "https://www.heart.org/en/healthy-living/healthy-eating/losing-weight"}],
        "cholesterol": [{"label": "AHA: cholesterol", "url": "https://www.heart.org/en/health-topics/cholesterol"}],
        "diabetes": [{"label": "AHA: diabetes & your heart", "url": "https://www.heart.org/en/health-topics/diabetes"}],
        "general": [{"label": "AHA healthy living", "url": "https://www.heart.org/en/healthy-living"}],
    },
    # National sets for a few countries (their own bodies); WHO supplements the rest.
    "ca": {
        "nutrition": [{"label": "Canada's Food Guide", "url": "https://food-guide.canada.ca/en/"}],
        "exercise": [{"label": "ParticipACTION (Canada)", "url": "https://www.participaction.com/"}],
        "smoking": [{"label": "Government of Canada: quit smoking", "url": "https://www.canada.ca/en/health-canada/services/smoking-tobacco/quit-smoking.html"}],
        "general": [{"label": "Heart & Stroke Foundation of Canada", "url": "https://www.heartandstroke.ca/healthy-living"}],
    },
    "au": {
        "nutrition": [{"label": "Eat for Health (Australia)", "url": "https://www.eatforhealth.gov.au/"}],
        "exercise": [{"label": "Australian physical-activity guidelines", "url": "https://www.health.gov.au/topics/physical-activity-and-exercise"}],
        "smoking": [{"label": "Quit (Australia)", "url": "https://www.quit.org.au/"}],
        "general": [{"label": "Heart Foundation (Australia)", "url": "https://www.heartfoundation.org.au/"}],
    },
    "ie": {
        "nutrition": [{"label": "Safefood (Ireland)", "url": "https://www.safefood.net/"}],
        "smoking": [{"label": "QUIT.ie (Ireland)", "url": "https://www.quit.ie/"}],
        "general": [{"label": "Irish Heart Foundation", "url": "https://irishheart.ie/"}],
    },
    "nz": {
        "smoking": [{"label": "Quitline (New Zealand)", "url": "https://quit.org.nz/"}],
        "general": [{"label": "Heart Foundation (New Zealand)", "url": "https://www.heartfoundation.org.nz/"}],
    },
    "who": {
        "nutrition": [{"label": "WHO healthy diet", "url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"}],
        "exercise": [{"label": "WHO physical activity guidance", "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity"}],
        "smoking": [{"label": "WHO tobacco facts & support", "url": "https://www.who.int/news-room/fact-sheets/detail/tobacco"}],
        "blood_pressure": [{"label": "WHO hypertension guidance", "url": "https://www.who.int/news-room/fact-sheets/detail/hypertension"}],
        "alcohol": [{"label": "WHO alcohol facts", "url": "https://www.who.int/news-room/fact-sheets/detail/alcohol"}],
        "weight": [{"label": "WHO overweight & obesity", "url": "https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight"}],
        "diabetes": [{"label": "WHO diabetes facts", "url": "https://www.who.int/news-room/fact-sheets/detail/diabetes"}],
        "general": [{"label": "WHO cardiovascular diseases", "url": "https://www.who.int/news-room/fact-sheets/detail/cardiovascular-diseases-(cvds)"}],
    },
}

# Country -> ordered list of resource sets to merge (own bodies first, then WHO).
COUNTRY_RESOURCE_SETS = {
    "United Kingdom": ["uk"],
    "United States": ["us"],
    "Canada": ["ca", "who"],
    "Australia": ["au", "who"],
    "Ireland": ["ie", "who"],
    "New Zealand": ["nz", "who"],
}

EXERCISE_NOTE = ("A basic free activity app (like a phone pedometer) is enough — a paid "
                 "fitness tracker is optional, not required.")

ACTIVITY_GUIDELINE_MIN = 150  # minutes/week of moderate activity (WHO/NHS)


def _resource_sets_for_country(country: str | None) -> list:
    """Which resource sets apply to a country: its own first, then WHO. Unknown
    countries get WHO (international) only."""
    return COUNTRY_RESOURCE_SETS.get(country or "", ["who"])


def _resources_for(topic: str, country: str | None):
    """Merge verified links for a topic across the country's sets (national first,
    then WHO), de-duplicated; falls back to the NHS set if nothing else exists."""
    out, seen = [], set()
    for set_name in _resource_sets_for_country(country):
        for link in RESOURCES.get(set_name, {}).get(topic, []):
            if link["url"] not in seen:
                seen.add(link["url"])
                out.append(link)
    if not out:  # last-resort accessible fallback (e.g. sleep / cholesterol topics)
        for link in RESOURCES["uk"].get(topic, []):
            if link["url"] not in seen:
                seen.add(link["url"])
                out.append(link)
    return out[:3]


def _attach_resources(recs: list, country: str | None) -> list:
    """Add a `resources` list (and a tracker note for exercise) to each recommendation."""
    for r in recs:
        topic = (r.get("topic") or "general").strip().lower()
        r["topic"] = topic
        r["resources"] = _resources_for(topic, country)
        if topic == "exercise":
            r["resource_note"] = EXERCISE_NOTE
    return recs


def _exercise_sufficient(supplementary: dict | None) -> bool:
    """True if the person already reports meeting activity guidelines."""
    if not supplementary:
        return False
    try:
        mins = float(supplementary.get("exercise_mins"))
    except (TypeError, ValueError):
        mins = None
    if mins is not None and mins >= ACTIVITY_GUIDELINE_MIN:
        return True
    try:
        steps = float(supplementary.get("steps"))
    except (TypeError, ValueError):
        steps = None
    return steps is not None and steps >= 12000


def build_user_message(result: dict, supplementary: dict | None) -> str:
    """Assemble the precomputed result + optional supplementary context for Claude."""
    factors = result.get("key_factors", [])
    factor_lines = []
    for f in factors:
        d = f.get("delta_points", 0)
        if f.get("direction") == "neutral" or d == 0:
            factor_lines.append(f"- {f['label']}: {f.get('detail','') or 'fixed factor'}")
        else:
            arrow = "raises" if d > 0 else "lowers"
            factor_lines.append(f"- {f['label']}: {arrow} the estimate by about "
                                f"{abs(d)} percentage points")

    supp = {k: v for k, v in (supplementary or {}).items() if v not in (None, "", [])}
    supp_text = "\n".join(f"- {k}: {v}" for k, v in supp.items()) or "- (none provided)"

    activity_line = ("ACTIVITY STATUS: The person ALREADY MEETS physical-activity guidelines — "
                     "do NOT recommend more exercise; acknowledge it and use that slot for "
                     "something else." if _exercise_sufficient(supplementary) else
                     "ACTIVITY STATUS: No evidence they meet activity guidelines.")

    missing = result.get("missing_inputs") or []
    estimated = [i.get("label", i.get("key", "")) for i in (result.get("estimated_inputs") or [])]
    replaced = missing + estimated
    missing_text = ", ".join(replaced) if replaced else "none"

    return f"""Here is the person's ALREADY-CALCULATED result. Restate the numbers exactly.

MODEL: {result.get('model_label')}
10-YEAR RISK: {result.get('risk_percent')}%
SCORE (0-100): {result.get('score_0_100')}
RISK BAND (use exactly this): {result.get('band')}
MODEL'S OWN CLINICAL NOTE: {result.get('clinical_note')}
EXTRA OUTPUTS: {json.dumps(result.get('extras', {}))}
MISSING INPUTS REPLACED WITH AVERAGES: {missing_text}

DETERMINISTIC FACTORS DRIVING THIS RESULT (do not invent others):
{chr(10).join(factor_lines) if factor_lines else '- (none)'}

SUPPLEMENTARY LIFESTYLE / WEARABLE CONTEXT (did NOT affect the score; use only to tailor advice):
{supp_text}

{activity_line}

Write the JSON object now."""


def _extract_json(text: str) -> dict:
    """Be forgiving: strip any stray fences and grab the outermost JSON object."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t.lstrip("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end + 1]
    return json.loads(t)


def get_advice(result: dict, supplementary: dict | None = None, country: str | None = None) -> dict:
    """Return advice dict. Uses Claude when configured; otherwise a static fallback.

    `country` selects which verified help links to attach (the person's national
    bodies first, then WHO to supplement). Unknown/None -> WHO international set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _static_fallback(result, reason="no_api_key", supplementary=supplementary, country=country)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=ADVICE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_message(result, supplementary)}],
        )
        text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
        advice = _extract_json(text)
        advice["source_mode"] = "claude"
        # Attach verified links ourselves (the model is told never to write URLs).
        advice["recommendations"] = _attach_resources(advice.get("recommendations", []), country)
        # Safety net: never let the model override the deterministic band/score.
        advice["band"] = result.get("band")
        advice["risk_percent"] = result.get("risk_percent")
        advice["score_0_100"] = result.get("score_0_100")
        return advice
    except Exception as e:  # noqa: BLE001 - any failure degrades gracefully
        return _static_fallback(result, reason=f"error:{type(e).__name__}",
                                supplementary=supplementary, country=country)


# ---- deterministic fallback ---------------------------------------------------
_SOURCES = {
    "smoking": ("Stopping smoking is the single biggest thing most people can do for heart risk.", "NHS"),
    "bp": ("Lower blood pressure reduces strain on arteries over time.", "BHF"),
    "cholesterol": ("Improving your cholesterol profile lowers long-term risk.", "NHS"),
    "weight": ("Reaching a healthier weight eases several risk factors at once.", "BHF"),
    "activity": ("Regular activity strengthens the heart and improves most risk factors.", "WHO"),
    "diet": ("A heart-healthy diet supports blood pressure, weight and cholesterol.", "AHA"),
}


def _static_fallback(result: dict, reason: str, supplementary: dict | None = None,
                     country: str | None = None) -> dict:
    band = result.get("band")
    risk = result.get("risk_percent")
    factors = result.get("key_factors", [])
    raising = [f for f in factors if f.get("direction") == "raises" and f.get("delta_points")]
    raising.sort(key=lambda f: abs(f.get("delta_points", 0)), reverse=True)

    key_factors = [f["label"] for f in factors[:5]] or ["Age", "Blood pressure", "Cholesterol"]

    recs = []
    labels = " ".join(f["label"].lower() for f in raising)
    if "smok" in labels:
        recs.append({"action": "Get free support to stop smoking", "why": _SOURCES["smoking"][0],
                     "topic": "smoking", "source": "NHS"})
    if "blood pressure" in labels or "systolic" in labels:
        recs.append({"action": "Have your blood pressure checked and tracked regularly", "why": _SOURCES["bp"][0],
                     "topic": "blood_pressure", "source": "BHF"})
    if "cholesterol" in labels:
        recs.append({"action": "Ask about a cholesterol (lipid) review", "why": _SOURCES["cholesterol"][0],
                     "topic": "cholesterol", "source": "NHS"})
    if "body mass" in labels or "bmi" in labels:
        recs.append({"action": "Work toward a healthier weight with small sustained changes", "why": _SOURCES["weight"][0],
                     "topic": "weight", "source": "BHF"})
    # Broadly-applicable basics, ranked after specifics. Skip the activity tip if
    # the person already meets activity guidelines.
    if not _exercise_sufficient(supplementary):
        recs.append({"action": "Aim for about 150 minutes of moderate activity each week", "why": _SOURCES["activity"][0],
                     "topic": "exercise", "source": "WHO"})
    recs.append({"action": "Build meals around vegetables, wholegrains, pulses and oily fish", "why": _SOURCES["diet"][0],
                 "topic": "nutrition", "source": "AHA"})
    recs = _attach_resources(recs[:6], country)

    interp = (f"Your estimated 10-year cardiovascular risk is {risk}%, in the '{band}' band — "
              f"an educational estimate based on what you entered, not a diagnosis.")
    if _exercise_sufficient(supplementary):
        interp += " You're already meeting activity guidelines, which is a strong protective habit."
    if result.get("missing_inputs") or result.get("estimated_inputs"):
        interp += " Some details were estimated, so treat it as a rough guide."

    return {
        "interpretation": interp,
        "key_factors": key_factors,
        "recommendations": recs,
        "closing_line": "Bring these results to a GP or clinician, who can give advice tailored to you.",
        "band": band, "risk_percent": risk, "score_0_100": result.get("score_0_100"),
        "source_mode": "fallback", "fallback_reason": reason,
    }
