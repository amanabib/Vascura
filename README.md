# Vascura

An **educational** web app that estimates 10-year cardiovascular risk using three
accredited models — **QRISK3** (UK), **SCORE2 / SCORE2-OP** (Europe) and the
**ASCVD Pooled Cohort Equations** (US) — and then uses Claude to explain the
result in plain English and suggest source-backed lifestyle steps.

> ⚠️ **This is a learning tool, not a medical device and not a diagnosis.** It
> exists to make a well-known piece of preventive science explorable. It must not
> be used to make any health decision. See *Medical disclaimer* below.

---

## What it does

1. **On first load, Vascura asks two things: your age and your country** (a
   dropdown). It then suggests the most relevant model for where you live — UK →
   QRISK3, Europe → SCORE2, US → ASCVD — shown first as **"Recommended for you"**,
   with any others listed below under **"Other available models"**. Models that
   aren't validated for your age are hidden: people **under 40 only see QRISK3**,
   because SCORE2 and ASCVD are validated from age 40.
2. You answer that model's questionnaire (your age is carried over from the intake
   screen). Every section (including **"About you"**) can be minimised, and optional
   "advanced" and "lifestyle" sections are collapsed by default and clearly labelled
   **"does not affect the score"** — they only enrich the written advice.
3. Don't know a value like your cholesterol or blood pressure? Tick **"Estimate
   from my age & sex"** and the app fills in a typical population figure so you can
   still explore the model. Estimated results are prominently flagged as less
   reliable (see *Estimating missing values* below).
4. The app computes the score **deterministically in Python** (never by the AI),
   shows the percentage, one of six calm risk bands, and — for QRISK3 — a heart
   age and relative risk.
5. Claude receives the *already-computed* score and your inputs, restates the
   number (it is told never to recalculate it), and returns a structured
   explanation plus 3–6 ranked recommendations. **Each recommendation carries
   verified "how to act on this" links** — NHS / BHF for UK users, AHA / federal
   sources for the US, WHO internationally (see *Actionable links* below). If you
   already report meeting activity guidelines, it **won't tell you to exercise
   more** — it acknowledges it and spends that slot elsewhere.

After you choose a model, a small citation of the **data pool** that model was
derived from is shown at the bottom of the screen. A **light / dark mode** toggle
sits in the top-right (it follows your device's preference by default; the dark
theme is a neutral grey).

### How it's served
Vascura is a single **Flask** app: `app.py` serves the bespoke HTML/CSS/JS interface
in `web/` and exposes a small JSON API the page calls. All the heavy lifting —
schemas, scoring, estimation, advice — lives in plain Python modules that `app.py`
imports. There is no build step and no second app to keep in sync. Deploy it free on
Render (or any host that runs a Python/WSGI app); see *Deploying* below.

---

## Architecture

```
        FRONT END
        ┌─────────────────────────────┐
        │ app.py  →  web/ (HTML/JS)   │
        │ bespoke UI, SVG gauge       │
        │ Flask JSON API + static     │
        │ host free on Render         │
        └──────────────┬──────────────┘
                       ▼  (import, not HTTP)
        ┌────────────────────────────────────────────────────────────────┐
        │  PYTHON CORE                                                   │
        │   schemas.py     one source of truth for every question        │
        │   estimate.py    fill a missing field from population averages  │
        │   scoring/       deterministic 10-year risk (no AI, testable)   │
        │     qrisk3.py · score2.py · ascvd.py · common.py (bands)        │
        │   advice.py      asks Claude to EXPLAIN the computed score,     │
        │                  then overrides band/score with the            │
        │                  deterministic values; static fallback if no    │
        │                  key. Key lives server-side only.               │
        └────────────────────────────────────────────────────────────────┘
                                         │ only if a key is set
                                         ▼
                              ┌────────────────────────┐
                              │  Anthropic API (Claude)│
                              └────────────────────────┘
```

The golden rule the whole design enforces: **the AI never produces the number.**
The score is computed in `scoring/`; the advice path recomputes it server-side and
writes the deterministic band/score back over whatever the model said. The AI is a
translator, not a calculator. (The original Flask request/response detail is
unchanged: `/api/models`, `/api/models/<key>`, `/api/score`, `/api/advice`,
`/api/health`, all recomputing server-side and rejecting out-of-range ages.)

---

## Estimating missing values

A layperson often doesn't know their cholesterol or blood pressure. Rather than
block them, the app can substitute a **typical value for someone of their age and
sex** (the same thing QRISK3 itself does internally for missing values), so the
model can still be explored. This is handled by `estimate.py`. Honesty is built in:

- Every estimated field is shown back to you, and the result carries a prominent
  **"some values were estimated"** banner telling you to treat it as a rough,
  population-typical figure rather than a personal one. The AI advice is told too.
- The figures are **approximate population averages by age band and sex**, in line
  with published adult health-survey statistics and the population means used by
  tools like QRISK3. They are **not** a fitted personal model, and a real measured
  value should always be preferred. (Where height and weight are known, systolic
  blood pressure gets a small, clearly-bounded adjustment for BMI, since that
  association is well-established in direction; cholesterol is left on age+sex.)
- If you want to refine the tables, they live in one place at the top of
  `estimate.py` and can be updated against the latest survey data.

---

## Choosing the right model for you

The intake screen (age + country) drives a small, shared piece of logic in
`regions.py`:

- **Country → region.** The UK maps to QRISK3, the broad European set to SCORE2,
  the US to ASCVD, and everywhere else to a sensible default (SCORE2). The full
  country list and mapping live at the top of `regions.py`.
- **Age gating.** Each model is only offered inside its validated age range
  (QRISK3 25–84, SCORE2 40–89, ASCVD 40–79). So an under-40 sees only QRISK3; an
  under-25 sees a short explanation that these tools aren't validated that young,
  and no score.
- **Why something is missing.** Whenever age removes a model from the list, the
  selection screen shows a brief one- or two-sentence note saying which models were
  hidden and why (e.g. *"SCORE2 / SCORE2-OP and ASCVD are only validated from age 40,
  so they are not shown for age 35."*), returned as `exclusion_note` from
  `regions.recommend()`.
- **Ordering.** The country-relevant model is returned first and flagged
  `recommended`; the rest follow under "Other available models". If your country's
  preferred model isn't valid for your age (e.g. a 35-year-old outside the UK), the
  app falls back to QRISK3 and tells you it's UK-calibrated so you read it as
  indicative.

Nationality is used **only** to pick and order the models (and to choose which
links to show); it is not stored and does not change the maths.

---

## Actionable links

Every AI recommendation is meant to be easy to act on, so the app attaches one or
two **verified links** to each one. Crucially, **the AI never writes the URLs** —
it only tags each recommendation with a topic (nutrition, exercise, smoking, blood
pressure, sleep, alcohol, weight, cholesterol, diabetes, general), and the backend
(`advice.py`, `RESOURCES`) looks up a curated, reputable link for that topic. This
prevents the model from inventing broken or untrustworthy links.

The links are **personalised to your country**. Each country maps (in
`COUNTRY_RESOURCE_SETS`) to its own national bodies first, then WHO to *supplement
or substitute* whatever the national set doesn't cover:
- **UK** → NHS and British Heart Foundation (Eatwell Guide, BHF recipe finder, the
  free **NHS Active 10** walking app, Couch to 5K, NHS Quit Smoking, NHS blood-
  pressure and sleep guidance, etc.).
- **US** → USDA MyPlate, AHA recipes/fitness/blood-pressure/sleep, smokefree.gov.
- **Canada / Australia / Ireland / New Zealand** → that country's own bodies
  (e.g. Canada's Food Guide, Australia's Eat for Health, Safefood Ireland, the
  national Heart Foundations and quit-smoking services) **plus WHO** for anything
  they don't cover.
- **Everywhere else** → WHO fact sheets, with NHS/BHF as accessible fallbacks for
  the couple of topics WHO doesn't cover (e.g. sleep).

Two deliberate rules: where a tool is suggested for activity, the app makes clear a
**fitness tracker is optional, not required** (it points at free options first); and
if your lifestyle answers show you already meet activity guidelines (≈150 min/week
or ≈12,000 steps/day), the **exercise recommendation is dropped** rather than nagging
you. The same links and rules apply whether the advice came from Claude or from the
offline static fallback.

---

## How it was built (chronological plan)

This was built MVP-first — get one correct number on screen, then widen.

1. **Pick a safe, simple stack.** Python + Flask serving plain HTML/CSS/JS (no
   build step), so it runs on a stock Mac with one command.
2. **Get one model numerically correct.** Port QRISK3 from the official ClinRisk
   C source by mechanically transpiling it to Python, then verify against 48
   published reference profiles before trusting it.
3. **Wrap it** with a clean interface: take friendly inputs, return a score, a
   band, key factors, heart age and relative risk.
4. **Add the six-band scale + 0–100 score** in `common.py` so every model speaks
   the same language to the UI.
5. **Add ASCVD**, verify against canonical reference values, then **add SCORE2 /
   SCORE2-OP** transcribed from a validated published implementation.
6. **Build the schema layer** (`schemas.py`) as the single source of truth for
   what each model asks, so the frontend can render any model generically.
7. **Build the frontend**: selection cards → questionnaire → gauge + result.
8. **Add the Claude advice layer** last, with a static fallback so the app is
   useful even with no API key.
9. **Write tests** (`tests/test_scoring.py`) and lock in the verification.
10. **Add the population estimator** (`estimate.py`) so unknown fields can be
    filled from age/sex averages, always flagged as less reliable.
11. **Polish the interface**: collapsible sections (including "About you"), a
    light/dark toggle, aligned form rows, per-model data-pool citations.
12. **Deploy the single Flask app** free on Render (blueprint + `Procfile`
    included), so there is one app to host and submit — no second build to keep
    in sync.

---

## Running it locally (MacBook Air M3 / Apple Silicon)

You need Python 3.11+ (macOS ships with a recent Python 3; `python3 --version`
to check).

**Option A — quick start (recommended for a first run):**

```bash
cd cvd-risk-app
pip3 install -r requirements.txt --break-system-packages
python3 app.py
```

`--break-system-packages` is the flag recent macOS/Homebrew Python needs to let
you install into the user environment. It sounds scary but is the normal,
expected way to do this for a one-off project like this.

**Option B — cleaner, isolated (recommended once you're comfortable):**

```bash
cd cvd-risk-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

A virtual environment (`venv`) keeps this project's packages separate from the
rest of your system. With Option B you don't need `--break-system-packages`.

Then open **http://localhost:5000** in your browser. That's it — you can explore
all three models immediately. Without an API key you'll get the static
(source-backed) advice; the scores are fully live either way.

To stop the server, press `Ctrl+C` in the terminal.

### Turning on live Claude advice

```bash
cp .env.example .env
```

Open `.env`, paste your key after `ANTHROPIC_API_KEY=`, save, and restart
`python app.py`. Get a key from <https://console.anthropic.com>. The key is read
by the **server** only and is never sent to the browser.

> The app reads `.env` automatically only if you've installed `python-dotenv`,
> or you can simply export the variable in your terminal before running:
> `export ANTHROPIC_API_KEY=sk-ant-...` then `python3 app.py`.

### Light / dark mode

The app has a **toggle in the top-right** of the header. It follows your device's
colour-scheme preference by default and flips for the session only — nothing is
stored, in keeping with the store-nothing design. The dark theme is a neutral grey.

---

## Deploying it (so others can use the link)

It's one Flask app, so any host that runs a Python/WSGI app works. The repo ships
with a Render blueprint (`render.yaml`) **and** a `Procfile`
(`web: gunicorn app:app --bind 0.0.0.0:$PORT`), so most hosts need zero extra setup.

> **Note on Streamlit Community Cloud:** it can't host this app. That platform only
> runs `streamlit run …` and serves Streamlit's own rendering engine — it can't
> serve a Flask app's HTML/CSS/JS UI. To keep this interface, host it as the Flask
> app below (Render's free tier is the easy path) and submit that URL.

### Render (free tier)

The included `render.yaml` targets **Render**.

1. Put this folder in a GitHub repository.
2. On <https://render.com>: **New → Blueprint**, choose your repo. Render reads
   `render.yaml` and creates the service (build `pip install -r requirements.txt`,
   start `gunicorn app:app`).
3. In the service's **Environment** tab, add `ANTHROPIC_API_KEY` with your real
   key. (It is marked `sync: false` in the blueprint so it never lives in your
   repo.)
4. Deploy. Render gives you a public `https://…onrender.com` URL.

Other free/cheap hosts (Railway, Fly.io, PythonAnywhere, etc.) work the same way —
they pick up the `Procfile` (or just run `gunicorn app:app`). On any of them, set
`ANTHROPIC_API_KEY` in the host's environment settings.

Free-tier services sleep after inactivity and take ~30s to wake on the first
request — fine for a competition demo.

---

## Cost

The app itself is free to host and free to run. The only variable cost is the
Claude API, and only when live advice is enabled.

| Item                         | Plan / basis                  | Cost                         |
|------------------------------|-------------------------------|------------------------------|
| Hosting (Render)            | Free tier                     | £0                           |
| Claude advice (per use)      | One short structured response | well under 1p per submission |
| Expected monthly total       | Light demo / judging use      | **< £3/month**, usually ≈ £0 |

Each advice call is one small request with a capped `max_tokens`, so individual
calls cost a fraction of a penny. To stay safe, set a **monthly spend cap** in
the Anthropic console (Billing → usage limits), and remember the app degrades to
free static advice rather than breaking if the key is missing or a limit is hit.
Choosing a cheaper model (e.g. a Haiku model via `ADVICE_MODEL`) reduces cost
further.

---

## Privacy & UK GDPR

Cardiovascular inputs are **special-category health data** under UK GDPR, which
deserves the highest care. The design choice here is the safest one: **store
nothing.**

- Inputs are held **in memory only** for the moment it takes to compute a score
  and generate advice, then discarded. There is **no database**.
- **No health inputs are written to logs.**
- The app sets **no cookies, no `localStorage`, no `sessionStorage`, and no
  analytics** — nothing persists in the browser between sessions (the colour theme
  is held in memory and resets on reload).
- If you enable Claude advice, the inputs are sent to the Anthropic API to
  generate the explanation. If you'd rather no data leave the machine at all,
  run it **without** an API key and it uses the static advice instead.
- **Estimated values never persist either** — they are computed for the single
  request and discarded with everything else.

Because nothing is stored or identifiable, the app avoids the heaviest GDPR
obligations by design rather than by policy. If you ever extend it to save
results, that calculus changes completely and you'd need a lawful basis,
explicit consent, and a privacy notice.

---

## Security

- **Secrets stay on the server.** The API key is read from an environment
  variable in `app.py` / `advice.py`. It is never embedded in the frontend and
  never sent to the browser. The browser only ever talks to your own backend.
- **The client is never trusted for the score.** `/api/advice` recomputes the
  score server-side from the raw inputs; it does not accept a score from the
  page. This means the displayed band can't be tampered with from the browser.
- `.env` is git-ignored so your key can't be committed by accident.

---

## A note on Garmin / wearables

The honest assessment: wiring up **official** Garmin Connect / Health API access
is **not realistic on a short timeline**. It requires applying for developer
access, OAuth approval, and review — weeks, not days, and approval isn't
guaranteed. Unofficial scraping would breach their terms and isn't appropriate
for a health tool.

So this app takes the pragmatic MVP route: the advanced/lifestyle fields
(resting heart rate, VO₂max, steps, sleep, etc.) are **manual entry**. You can
read them off your watch and type them in. Crucially, these values **never change
the risk score** — the validated models don't take them — they only give Claude
extra context to personalise the written advice. That keeps the science honest
while still letting wearable data be useful. A future version could add a real
Garmin OAuth integration to auto-fill those same fields.

---

## How accurate are the numbers? (verification)

Be appropriately sceptical of any tool that puts a health number on screen.
Here's exactly how far each engine was checked, stated honestly:

- **QRISK3 — numerically verified.** The engine is a faithful port of the
  official ClinRisk C source and was checked against **48 published reference
  profiles**: all 48 match, with a worst-case difference of **0.045 percentage
  points** (rounding-level). This is the strongest verification of the three.
- **ASCVD Pooled Cohort Equations — numerically verified.** Checked against the
  **canonical reference values** for the four race/sex groups; all match, worst
  case **0.005 percentage points**.
- **SCORE2 / SCORE2-OP — faithfully transcribed, sanity-checked.** Transcribed
  verbatim from a validated, published implementation of the ESC-2021 formulas.
  No official machine-readable reference table exists to diff against, so it was
  verified by internal consistency, correct age-band routing (SCORE2 vs
  SCORE2-OP), and monotonicity. **Recommended check:** confirm a few outputs
  against the official ESC **HeartScore** calculator (<https://heartscore.escardio.org>)
  before relying on it. UK is treated as a **low-risk** region.

Running the checks yourself:

```bash
python3 tests/test_scoring.py
# or, if you have pytest:  pytest tests/
```

---

## Medical disclaimer

This application is for **education and general information only**. It is **not a
medical device**, it does **not** provide medical advice, diagnosis or treatment,
and it must **not** be used to make any health or treatment decision. Risk
estimates are population-level statistics and do not predict what will happen to
any individual. Always consult a qualified clinician (e.g. your GP) about your
heart health. If you have symptoms such as chest pain or breathlessness, seek
urgent medical care.

### Regulatory note (MHRA)

In the UK, software that calculates or interprets risk *for the purpose of
informing clinical decisions about an individual* can fall within the definition
of a medical device regulated by the **MHRA**. This project is deliberately built
to stay on the **education** side of that line: it is framed as a learning tool,
carries prominent disclaimers, does not target patients or clinicians for
clinical use, and does not tell anyone what to do. If it were ever repurposed for
actual clinical use or marketed as a way to guide real decisions, it would likely
require MHRA registration and conformity assessment, and would need to be treated
as a regulated medical device.

---

## Attribution

QRISK3® is the work of ClinRisk Ltd. The QRISK3 algorithm source is used under
its open-source licence; see `scoring/QRISK3_CLINRISK_LICENSE.txt` for the full
notice that must accompany any use. SCORE2/SCORE2-OP are from the European
Society of Cardiology (2021). The ASCVD Pooled Cohort Equations are from the
2013 ACC/AHA guideline. Lifestyle guidance cites the NHS, British Heart
Foundation, ESC, AHA and WHO. The data pool each model was derived from is cited
in-app on the model's screen (and defined in `schemas.py`).

---

© Aman Abib 2026
