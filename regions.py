"""
regions.py — nationality -> region mapping and model recommendation/gating.

Used by both front ends so the logic lives in one place:
  * which of the three models are AGE-APPROPRIATE for a person, and
  * which one is most relevant to their country (shown first as "recommended"),
  * which resource set (UK / US / international) to attach to AI advice.

Regions:
  uk      -> QRISK3 is the home model
  europe  -> SCORE2 / SCORE2-OP is the home model
  us      -> ASCVD is the home model
  other   -> no perfectly-validated model; SCORE2 is offered as the general default
"""
from __future__ import annotations
import schemas

# Country -> region. UK is its own region; the SCORE2 "europe" set is broad.
_EUROPE = [
    "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland",
    "France", "Germany", "Greece", "Hungary", "Iceland", "Ireland", "Italy", "Kosovo",
    "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta", "Moldova", "Monaco",
    "Montenegro", "Netherlands", "North Macedonia", "Norway", "Poland", "Portugal",
    "Romania", "Russia", "San Marino", "Serbia", "Slovakia", "Slovenia", "Spain",
    "Sweden", "Switzerland", "Ukraine",
]
_OTHER = [
    "Algeria", "Argentina", "Australia", "Bangladesh", "Brazil", "Canada", "Chile",
    "China", "Colombia", "Egypt", "Ethiopia", "Ghana", "Hong Kong", "India", "Indonesia",
    "Iran", "Iraq", "Israel", "Japan", "Jordan", "Kenya", "Kuwait", "Lebanon", "Malaysia",
    "Mexico", "Morocco", "Nepal", "New Zealand", "Nigeria", "Pakistan", "Peru",
    "Philippines", "Qatar", "Saudi Arabia", "Singapore", "South Africa", "South Korea",
    "Sri Lanka", "Taiwan", "Tanzania", "Thailand", "Tunisia", "Turkey",
    "United Arab Emirates", "Uganda", "Vietnam", "Other / not listed",
]

_REGION = {"United Kingdom": "uk", "United States": "us"}
for _c in _EUROPE:
    _REGION[_c] = "europe"
for _c in _OTHER:
    _REGION[_c] = "other"

# Sorted dropdown list, but with the three "home" countries surfaced at the top.
_TOP = ["United Kingdom", "United States"]
_ALL_SORTED = sorted(_REGION.keys())
COUNTRIES = _TOP + [c for c in _ALL_SORTED if c not in _TOP]

# Region -> the model it "prefers".
_PREFERRED = {"uk": "qrisk3", "europe": "score2", "us": "ascvd", "other": "score2"}


def region_for(country: str | None) -> str:
    return _REGION.get(country or "", "other")


def resource_region(region: str) -> str:
    """Which curated resource set to use for advice links."""
    if region == "uk":
        return "uk"
    if region == "us":
        return "us"
    return "int"   # europe + other -> international (WHO + accessible)


def recommend(age, country):
    """
    Decide which models to show and in what order.

    Returns a dict:
      { "region": str,
        "available": [ {model meta + "recommended": bool} ... ]  # ordered, recommended first
        "recommended_key": str | None,
        "message": str | None }   # shown when there is a caveat or nothing fits
    """
    region = region_for(country)
    try:
        age = float(age)
    except (TypeError, ValueError):
        age = None

    metas = schemas.model_list()
    by_key = {m["key"]: m for m in metas}

    # age-appropriate models (this is what removes the 40+ models for under-40s)
    if age is None:
        available_keys = [m["key"] for m in metas]
    else:
        available_keys = [m["key"] for m in metas if m["age_min"] <= age <= m["age_max"]]

    message = None
    if not available_keys:
        if age is not None and age < 25:
            message = ("These calculators are not validated for people under 25, so no estimate "
                       "is shown. Cardiovascular risk tools become meaningful from age 40 (and "
                       "from 25 for the UK's QRISK3).")
        else:
            message = "No model in this tool is validated for that age, so no estimate is shown."
        return {"region": region, "available": [], "recommended_key": None,
                "message": message, "exclusion_note": None}

    preferred = _PREFERRED.get(region, "score2")
    if preferred in available_keys:
        rec_key = preferred
    else:
        # preferred model isn't age-appropriate (e.g. under-40 outside the UK).
        rec_key = "qrisk3" if "qrisk3" in available_keys else available_keys[0]
        if region != "uk" and rec_key == "qrisk3":
            message = ("Only QRISK3 is validated for people under 40. It is calibrated for UK "
                       "populations, so treat the figure as indicative if you live elsewhere.")

    ordered_keys = [rec_key] + [k for k in available_keys if k != rec_key]
    available = []
    for k in ordered_keys:
        m = dict(by_key[k])
        m["recommended"] = (k == rec_key)
        available.append(m)

    # Briefly explain any models hidden purely because of age, so the choice is clear.
    exclusion_note = None
    if age is not None:
        excluded = [m for m in metas if not (m["age_min"] <= age <= m["age_max"])]
        if excluded and available_keys:
            below = [m for m in excluded if age < m["age_min"]]
            above = [m for m in excluded if age > m["age_max"]]
            parts = []
            if below:
                names = _names(below)
                mn = min(m["age_min"] for m in below)
                parts.append(f"{names} {'is' if len(below) == 1 else 'are'} only validated from "
                             f"age {mn}, so {'it is' if len(below) == 1 else 'they are'} not shown for age {int(age)}")
            if above:
                names = _names(above)
                mx = max(m["age_max"] for m in above)
                parts.append(f"{names} {'is' if len(above) == 1 else 'are'} only validated up to "
                             f"age {mx}, so {'it is' if len(above) == 1 else 'they are'} not shown")
            exclusion_note = "; ".join(parts) + "."

    return {"region": region, "available": available, "recommended_key": rec_key,
            "message": message, "exclusion_note": exclusion_note}


def _names(metas: list) -> str:
    """Join model display names: 'A', 'A and B', or 'A, B and C'."""
    names = [m["name"] for m in metas]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"
