"""
app.py — Flask backend.

Serves the static frontend AND three JSON endpoints:
  GET  /api/models           -> list of models for the selection screen
  GET  /api/models/<key>     -> full questionnaire schema for one model
  POST /api/score            -> deterministic 10-year risk (computed here, in Python)
  POST /api/advice           -> Claude advice; score is RECOMPUTED server-side first

Design / privacy:
  * The score is ALWAYS computed on the server from the raw inputs. The browser can
    display a score but can never make the advice layer trust a tampered number —
    /api/advice recomputes from inputs before asking Claude to explain it.
  * The Anthropic API key lives only in the server environment; it is never sent to
    the browser.
  * Nothing is stored. Health data lives only for the duration of a request, in
    memory. There is no database and no logging of personal inputs.
"""
from __future__ import annotations
import os
from flask import Flask, jsonify, request, send_from_directory

import schemas
import advice as advice_layer
import estimate as estimator
import regions
from scoring import score as compute_score

APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")

app = Flask(__name__, static_folder=None)


# ---- frontend ----------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:filename>")
def web_assets(filename):
    return send_from_directory(WEB_DIR, filename)


# ---- API ---------------------------------------------------------------------
@app.route("/api/models")
def api_models():
    return jsonify({"models": schemas.model_list()})


@app.route("/api/models/<key>")
def api_model_schema(key):
    schema = schemas.model_schema(key)
    if schema is None:
        return jsonify({"error": f"Unknown model '{key}'."}), 404
    return jsonify(schema)


@app.route("/api/countries")
def api_countries():
    return jsonify({"countries": regions.COUNTRIES})


@app.route("/api/recommend")
def api_recommend():
    """Given age + country, return age-appropriate models ordered with the most
    country-relevant one first (flagged recommended)."""
    age = request.args.get("age")
    country = request.args.get("country")
    return jsonify(regions.recommend(age, country))


def _run_score(payload):
    """Shared: validate, optionally fill estimable fields, compute a ScoreResult.

    Returns (result, estimated_info, err). `estimated_info` lists any population
    averages substituted in (empty if none / on error)."""
    model = (payload or {}).get("model")
    inputs = (payload or {}).get("inputs") or {}
    estimate_keys = (payload or {}).get("estimate") or []
    if not model:
        return None, [], ("Missing 'model'.", 400)
    if model not in schemas.MODELS:
        return None, [], (f"Unknown model '{model}'.", 400)
    if "sex" not in inputs or "age" not in inputs:
        return None, [], ("Sex and age are required.", 400)

    # Fill any requested estimable fields from population averages BEFORE scoring.
    inputs, estimated_info, est_warnings = estimator.apply_estimates(inputs, estimate_keys)

    try:
        result = compute_score(model, inputs)
    except (KeyError, ValueError, TypeError) as e:
        return None, [], (f"Could not score: {e}", 400)

    # Record the substitutions on the result so the UI can flag reliability.
    result.estimated_inputs = estimated_info
    if est_warnings:
        result.warnings = list(result.warnings) + est_warnings
    return result, estimated_info, None


@app.route("/api/score", methods=["POST"])
def api_score():
    result, _info, err = _run_score(request.get_json(silent=True))
    if err:
        msg, code = err
        return jsonify({"error": msg}), code
    return jsonify(result.to_dict())


@app.route("/api/advice", methods=["POST"])
def api_advice():
    payload = request.get_json(silent=True) or {}
    result, _info, err = _run_score(payload)   # recompute server-side; never trust client score
    if err:
        msg, code = err
        return jsonify({"error": msg}), code
    if not result.in_valid_age_range:
        return jsonify({"error": "Age is outside this model's validated range; no advice generated.",
                        "result": result.to_dict()}), 400
    supplementary = payload.get("supplementary") or {}
    advice = advice_layer.get_advice(result.to_dict(), supplementary,
                                     country=payload.get("nationality"))
    return jsonify({"result": result.to_dict(), "advice": advice})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "advice_enabled": bool(os.environ.get("ANTHROPIC_API_KEY"))})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug stays off by default; set FLASK_DEBUG=1 locally if you want autoreload.
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
