/* ============================================================================
   Vascura — app logic
   No localStorage / sessionStorage; all state (including the colour theme)
   lives in memory and resets on reload. Theme defaults to the OS preference.
   ============================================================================ */
"use strict";

const BANDS = [
  { label: "Low risk",            lo: 0,    hi: 5,    color: "var(--b0)" },
  { label: "Relatively low risk", lo: 5,    hi: 7.5,  color: "var(--b1)" },
  { label: "Moderate risk",       lo: 7.5,  hi: 10,   color: "var(--b2)" },
  { label: "Relatively high risk",lo: 10,   hi: 20,   color: "var(--b3)" },
  { label: "High risk",           lo: 20,   hi: 30,   color: "var(--b4)" },
  { label: "Very high risk",      lo: 30,   hi: Infinity, color: "var(--b5)" },
];

const state = { modelKey: null, schema: null, userAge: null, nationality: null };

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
};

/* ---- colour theme (session-only; no storage) ---- */
function initTheme() {
  const btn = $("#theme-toggle");
  if (!btn) return;
  const sync = () => btn.setAttribute("aria-pressed",
    String(document.documentElement.getAttribute("data-theme") === "dark"));
  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
    sync();
  });
  sync();
}

function showView(id) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("is-active"));
  $("#" + id).classList.add("is-active");
  window.scrollTo({ top: 0, behavior: "smooth" });
  const h = $("#" + id).querySelector("h1,h2");
  if (h) h.setAttribute("tabindex", "-1"), h.focus({ preventScroll: true });
}

/* ---- 0. intake (age + country) -> recommendation ---- */
async function loadCountries() {
  try {
    const { countries } = await (await fetch("/api/countries")).json();
    const sel = $("#intake-country");
    countries.forEach(c => sel.append(el("option", { value: c }, c)));
  } catch (e) { /* dropdown still has the placeholder */ }
}

function initIntake() {
  const form = $("#intake-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#intake-error");
    const age = parseInt($("#intake-age").value, 10);
    const country = $("#intake-country").value;
    if (!age || age < 18 || age > 100 || !country) {
      err.textContent = !country ? "Please choose your country."
        : "Please enter a valid age (18–100).";
      err.hidden = false;
      return;
    }
    err.hidden = true;
    state.userAge = age;
    state.nationality = country;
    await runRecommend(age, country);
    showView("view-select");
  });
}

function modelCard(m) {
  const children = [];
  if (m.recommended) children.push(el("span", { class: "rec-badge" }, "Recommended for you"));
  children.push(
    el("span", { class: "age-tag" }, `Ages ${m.age_min}-${m.age_max}`),
    el("h3", {}, m.name),
    el("p", { class: "one-liner" }, m.one_liner),
    el("ul", {}, ...m.bullets.map(b => el("li", {}, b))),
    el("span", { class: "choose" }, "Use this model →"));
  return el("button", {
    class: "model-card" + (m.recommended ? " is-recommended" : ""),
    type: "button", role: "listitem", onclick: () => selectModel(m.key),
  }, ...children);
}

async function runRecommend(age, country) {
  const recWrap = $("#recommended-wrap"), othWrap = $("#others-wrap"), msg = $("#select-message");
  const recHost = $("#recommended-cards"), othHost = $("#other-cards");
  recHost.innerHTML = ""; othHost.innerHTML = "";
  recWrap.hidden = true; othWrap.hidden = true; msg.hidden = true;
  let data;
  try {
    data = await (await fetch(`/api/recommend?age=${encodeURIComponent(age)}&country=${encodeURIComponent(country)}`)).json();
  } catch (e) {
    msg.hidden = false; msg.textContent = "Could not load models. Is the server running?";
    return;
  }
  if (data.message) { msg.hidden = false; msg.textContent = data.message; }
  const exEl = $("#select-exclusion");
  if (exEl) {
    if (data.exclusion_note) { exEl.hidden = false; exEl.textContent = data.exclusion_note; }
    else { exEl.hidden = true; exEl.textContent = ""; }
  }
  const available = data.available || [];
  const recommended = available.filter(m => m.recommended);
  const others = available.filter(m => !m.recommended);
  if (recommended.length) {
    recommended.forEach(m => recHost.append(modelCard(m)));
    recWrap.hidden = false;
  }
  if (others.length) {
    others.forEach(m => othHost.append(modelCard(m)));
    othWrap.hidden = false;
  }
  // if nothing is recommended but some are available, still show them as "available"
  if (!recommended.length && others.length) {
    $("#others-wrap").querySelector(".section-label").textContent = "Available models";
  }
}

/* ---- 2. questionnaire ---- */
async function selectModel(key) {
  const res = await fetch("/api/models/" + key);
  if (!res.ok) return;
  state.modelKey = key;
  state.schema = await res.json();
  renderForm();
  showView("view-form");
}

function fieldNode(f) {
  if (f.sex && f.sex !== "any") f._conditionalSex = f.sex; // erectile dysfunction etc. handled at collect time
  if (f.type === "boolean") {
    const input = el("input", { type: "checkbox", id: "f_" + f.key, "data-key": f.key });
    return el("div", { class: "field field-bool", "data-sexonly": f.sex || "" },
      el("label", { class: "bool-label", for: "f_" + f.key }, input, f.label));
  }
  const labelChildren = [f.label];
  if (f.optional) labelChildren.push(el("span", { class: "help", style: "display:inline;margin-left:6px" }, "(optional)"));
  const label = el("label", { for: "f_" + f.key }, ...labelChildren);
  let control, numInput = null;
  if (f.type === "select") {
    control = el("select", { id: "f_" + f.key, "data-key": f.key },
      ...f.options.map(o => el("option", { value: o.value }, o.label)));
  } else { // number
    numInput = el("input", { type: "number", id: "f_" + f.key, "data-key": f.key,
      min: f.min, max: f.max, step: f.step || 1, inputmode: "decimal",
      placeholder: f.optional ? "—" : "" });
    control = f.unit
      ? el("div", { class: "unit-wrap" }, numInput, el("span", { class: "unit" }, f.unit))
      : numInput;
  }
  const node = el("div", { class: "field" }, label, control);
  if (f.help) node.append(el("span", { class: "help" }, f.help));

  // "Estimate this" control for fields we can fill from population averages.
  if (f.estimable && numInput) {
    const chk = el("input", { type: "checkbox", id: "est_" + f.key, "data-estimate-for": f.key });
    const toggle = el("label", { class: "estimate-toggle", for: "est_" + f.key },
      chk, "Estimate from my age & sex");
    chk.addEventListener("change", () => {
      if (chk.checked) {
        node.classList.add("is-estimated");
        toggle.classList.add("on");
        numInput.value = "";
        numInput.disabled = true;
      } else {
        node.classList.remove("is-estimated");
        toggle.classList.remove("on");
        numInput.disabled = false;
      }
    });
    node.append(toggle);
  }
  return node;
}

function collapsible(title, { open = false, tag = null } = {}) {
  const summary = el("summary", {}, title);
  if (tag) summary.append(el("span", { class: "supp-tag" }, tag));
  const details = el("details", open ? { open: "" } : {}, summary);
  return { details, summary };
}

function renderForm() {
  const s = state.schema;
  $("#form-h").textContent = s.name;
  $("#form-oneliner").textContent = s.one_liner;

  const host = $("#form-sections");
  host.innerHTML = "";
  s.sections.forEach(sec => {
    const body = el("div", { class: "fs-body" });
    if (sec.subtitle) body.append(el("p", { class: "fs-sub" }, sec.subtitle));
    const grid = el("div", { class: "fields" });
    sec.fields.forEach(f => grid.append(fieldNode(f)));
    body.append(grid);
    // core sections are collapsible but OPEN by default (so "About you" can be minimised)
    const details = el("details", { class: "fs", open: "" }, el("summary", {}, sec.title), body);
    host.append(details);
  });

  // supplementary collapsibles (collapsed by default)
  const supHost = $("#supp-sections");
  supHost.innerHTML = "";
  (s.supplementary || []).forEach(sup => {
    const body = el("div", { class: "supp-body" }, el("p", { class: "supp-note" }, sup.note));
    const grid = el("div", { class: "fields" });
    sup.fields.forEach(f => grid.append(fieldNode(f)));
    body.append(grid);
    const details = el("details", { class: "supp" },
      el("summary", {}, sup.title, el("span", { class: "supp-tag" }, "Does not affect score")),
      body);
    supHost.append(details);
  });

  // sex-conditional fields (e.g. erectile dysfunction) toggle on sex change
  const sexSel = $('#f_sex');
  if (sexSel) {
    const applySex = () => {
      document.querySelectorAll('[data-sexonly]').forEach(node => {
        const only = node.getAttribute('data-sexonly');
        node.style.display = (!only || only === sexSel.value) ? "" : "none";
      });
    };
    sexSel.addEventListener("change", applySex);
    applySex();
  }

  // carry the age from the intake screen into the questionnaire
  const ageInput = $('#f_age');
  if (ageInput && state.userAge != null) ageInput.value = state.userAge;

  renderCitation("form-citation");
  $("#form-error").hidden = true;
}

/* data-pool citation (small print) */
function renderCitation(hostId) {
  const host = document.getElementById(hostId);
  if (!host) return;
  const cite = state.schema && state.schema.cohort_citation;
  if (!cite) { host.hidden = true; return; }
  host.hidden = false;
  host.innerHTML = "";
  host.append(el("strong", {}, "Data pool: "), cite + " ");
  const url = state.schema && state.schema.cohort_source_url;
  if (url) host.append(el("a", { href: url, target: "_blank", rel: "noopener" }, "Source ↗"));
}

function collectInputs() {
  const core = {}, supp = {}, estimate = [];
  const suppKeys = new Set();
  (state.schema.supplementary || []).forEach(s => s.fields.forEach(f => suppKeys.add(f.key)));

  // which fields the person asked us to estimate (skip hidden sex-only ones)
  document.querySelectorAll('[data-estimate-for]').forEach(chk => {
    if (!chk.checked) return;
    const key = chk.getAttribute("data-estimate-for");
    const wrap = document.querySelector(`#f_${key}`)?.closest('[data-sexonly]');
    if (wrap && wrap.style.display === "none") return;
    estimate.push(key);
  });

  document.querySelectorAll('[data-key]').forEach(node => {
    const key = node.getAttribute("data-key");
    const wrapper = node.closest('[data-sexonly]');
    if (wrapper && wrapper.style.display === "none") return; // skip hidden sex-only fields
    let val;
    if (node.type === "checkbox") val = node.checked;
    else if (node.disabled) return;          // estimated fields are disabled -> filled server-side
    else if (node.value === "") return;      // leave blank/optional out
    else if (node.tagName === "SELECT") val = node.value;
    else val = parseFloat(node.value);
    if (val === "" || (typeof val === "number" && Number.isNaN(val))) return;
    (suppKeys.has(key) ? supp : core)[key] = val;
  });
  return { inputs: core, supplementary: supp, estimate };
}

/* ---- 3. submit & results ---- */
$("#risk-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errBox = $("#form-error");
  const { inputs, supplementary, estimate } = collectInputs();
  const estimateSet = new Set(estimate);

  // minimal client validation: required (non-optional, non-estimated) fields present
  const missing = [];
  state.schema.sections.forEach(sec => sec.fields.forEach(f => {
    if (f.optional || f.type === "boolean") return;
    if (estimateSet.has(f.key)) return; // will be filled from population averages
    const wrap = document.querySelector(`#f_${f.key}`)?.closest('[data-sexonly]');
    if (wrap && wrap.style.display === "none") return;
    if (!(f.key in inputs)) missing.push(f.label);
  }));
  if (missing.length) {
    errBox.textContent = "Please complete (or tick \u201cEstimate\u201d for): " + missing.join(", ") + ".";
    errBox.hidden = false;
    errBox.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  errBox.hidden = true;

  showView("view-result");
  $("#result-invalid").hidden = true;
  $("#estimate-banner").hidden = true;
  $("#result-main").hidden = true;

  let scoreData;
  try {
    const res = await fetch("/api/score", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: state.modelKey, inputs, estimate }),
    });
    scoreData = await res.json();
    if (!res.ok) throw new Error(scoreData.error || "Scoring failed");
  } catch (err) {
    $("#result-invalid").hidden = false;
    $("#result-invalid").textContent = "Sorry — " + err.message;
    return;
  }

  if (!scoreData.in_valid_age_range) {
    const n = $("#result-invalid");
    n.hidden = false;
    n.innerHTML = "";
    n.append(el("strong", {}, "No reliable estimate for this age. "),
      document.createTextNode(scoreData.clinical_note ||
        "The selected model is not validated for this age."));
    return;
  }

  renderResult(scoreData);
  $("#result-main").hidden = false;
  fetchAdvice(inputs, supplementary, estimate);
});

function renderEstimateBanner(d) {
  const host = $("#estimate-banner");
  const est = d.estimated_inputs || [];
  if (!est.length) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.innerHTML = "";
  host.append(el("strong", {}, "Heads up — some values were estimated. "));
  host.append(document.createTextNode(
    "The following were filled in from typical population averages for your age and sex, " +
    "so treat this result as a rough, population-typical figure rather than a personal one:"));
  const ul = el("ul", {});
  est.forEach(i => ul.append(el("li", {}, `${i.label}: ${i.value}${i.unit ? " " + i.unit : ""}`)));
  host.append(ul);
}

function renderResult(d) {
  renderEstimateBanner(d);

  $("#gauge-host").innerHTML = buildGauge(d.risk_percent, d.band_index);
  $("#risk-pct").textContent = d.risk_percent + "%";
  const bp = $("#band-pill");
  bp.textContent = d.band;
  bp.style.background = BANDS[d.band_index]?.color || "var(--teal)";

  // extras (heart age, relative risk)
  const ex = $("#extras-row");
  ex.innerHTML = "";
  const extras = d.extras || {};
  if (extras.heart_age !== undefined && extras.heart_age !== null) {
    ex.append(extraChip(extras.heart_age, "Estimated heart age", "yrs"));
  }
  if (extras.relative_risk !== undefined && extras.relative_risk !== null) {
    ex.append(extraChip("×" + extras.relative_risk, "vs a healthy peer your age"));
  }
  if (extras.variant) {
    ex.append(extraChip(extras.variant, "model used"));
  }

  $("#clinical-note").textContent = d.clinical_note || "";

  // factor bars
  const fx = $("#factors");
  fx.innerHTML = "";
  fx.append(el("h3", {}, "What's shaping this number"));
  const drivers = (d.key_factors || []).filter(f => f.delta_points || f.direction === "neutral").slice(0, 7);
  const maxDelta = Math.max(0.5, ...drivers.map(f => Math.abs(f.delta_points || 0)));
  drivers.forEach(f => {
    const cls = f.direction === "raises" ? "raises" : f.direction === "lowers" ? "lowers" : "fixed";
    const pct = Math.min(100, (Math.abs(f.delta_points || 0) / maxDelta) * 100);
    const deltaTxt = (f.delta_points)
      ? (f.delta_points > 0 ? "+" : "") + f.delta_points + " pts"
      : "fixed";
    fx.append(el("div", { class: "factor " + cls },
      el("span", { class: "f-label" }, f.label),
      el("span", { class: "f-delta" }, deltaTxt),
      el("div", { class: "f-bar" }, el("span", { style: `width:${f.delta_points ? pct : 18}%` })),
    ));
  });

  renderDisclaimer(d);
  renderCitation("result-citation");
}

function extraChip(val, label, unit) {
  return el("div", { class: "extra-chip" },
    el("div", { class: "ec-val" }, String(val) + (unit ? " " + unit : "")),
    el("div", { class: "ec-label" }, label));
}

/* ---- SVG band gauge (signature element) ----
   Six equal segments on a top semicircle; a marker sits in the band the person
   falls into, positioned by where their risk lands within that band. The exact
   percentage is shown separately, so nothing is distorted. */
function buildGauge(risk, bandIndex) {
  const W = 300, H = 178, cx = W / 2, cy = 158, r = 120, sw = 22;
  const polar = (deg) => {
    const rad = (deg * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
  };
  const arcPath = (a0, a1) => {
    const [x0, y0] = polar(a0), [x1, y1] = polar(a1);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  // segments: band i spans [180 - i*30, 180 - (i+1)*30]; sweep flag 1 goes clockwise (over the top)
  let segs = "";
  for (let i = 0; i < 6; i++) {
    const a0 = 180 - i * 30 - 2;     // small gap
    const a1 = 180 - (i + 1) * 30 + 2;
    segs += `<path d="${arcPath(a0, a1)}" stroke="${BANDS[i].color}" stroke-width="${sw}" fill="none" stroke-linecap="round" opacity="${i === bandIndex ? 1 : 0.32}"/>`;
  }
  // marker position: fraction within band
  const b = BANDS[bandIndex];
  let frac;
  if (!isFinite(b.hi)) frac = Math.min((risk - b.lo) / 20, 1);      // top band: cap at +20pp
  else frac = Math.max(0, Math.min(1, (risk - b.lo) / (b.hi - b.lo)));
  const markerAngle = 180 - (bandIndex + frac) * 30;
  const [mx, my] = polar(markerAngle);
  const [ix, iy] = (() => { const rad = markerAngle * Math.PI / 180; const ri = r - sw / 2 - 14; return [cx + ri * Math.cos(rad), cy - ri * Math.sin(rad)]; })();

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Risk gauge showing ${BANDS[bandIndex].label}">
    ${segs}
    <line x1="${cx}" y1="${cy}" x2="${ix.toFixed(2)}" y2="${iy.toFixed(2)}" stroke="var(--ink)" stroke-width="3" stroke-linecap="round"/>
    <circle cx="${mx.toFixed(2)}" cy="${my.toFixed(2)}" r="9" fill="var(--paper-2)" stroke="var(--ink)" stroke-width="3"/>
    <circle cx="${cx}" cy="${cy}" r="7" fill="var(--ink)"/>
    <text x="${cx - r}" y="${cy + 20}" font-size="11" fill="var(--ink-faint)" text-anchor="middle">lower</text>
    <text x="${cx + r}" y="${cy + 20}" font-size="11" fill="var(--ink-faint)" text-anchor="middle">higher</text>
  </svg>`;
}

/* ---- disclaimer (model-specific; QRISK3 carries the required ClinRisk notice) ---- */
function renderDisclaimer(d) {
  const host = $("#disclaimer");
  host.innerHTML = "";
  const common = el("p", {},
    el("strong", {}, "Remember: "),
    "this is an educational estimate, not a diagnosis or a medical-device output. " +
    "Risk models describe averages for groups of similar people and can be wrong for any " +
    "individual. Discuss anything about your own health with a GP or clinician.");
  host.append(common);

  if (d.model === "QRISK3") {
    // ClinRisk LGPL requires this disclaimer to be shown alongside any QRISK3 score.
    host.append(el("p", {},
      el("strong", {}, "About this QRISK3 calculation. "),
      "QRISK3® was produced by ",
      el("a", { href: "https://qrisk.org", target: "_blank", rel: "noopener" }, "ClinRisk Ltd"),
      " and is used here under its open-source licence to implement the algorithm faithfully. " +
      "ClinRisk accepts no responsibility for how the algorithm is used here, and this " +
      "implementation has not been certified. Please verify any result against the official " +
      "calculator at ",
      el("a", { href: "https://qrisk.org", target: "_blank", rel: "noopener" }, "qrisk.org"),
      "."));
  } else if (d.model === "SCORE2") {
    host.append(el("p", {}, el("strong", {}, "About this SCORE2 calculation. "),
      "Implements the European Society of Cardiology SCORE2 / SCORE2-OP algorithm (2021), " +
      "calibrated here to a low-risk region (the UK). Verify against the ESC HeartScore tool " +
      "for clinical use."));
  } else if (d.model === "ASCVD") {
    host.append(el("p", {}, el("strong", {}, "About this ASCVD calculation. "),
      "Implements the ACC/AHA 2013 Pooled Cohort Equations. These were derived mainly in US " +
      "populations and may fit other groups less well."));
  }
}

/* ---- advice layer ---- */
async function fetchAdvice(inputs, supplementary, estimate) {
  const host = $("#advice");
  host.innerHTML = '<div class="advice-loading">Preparing your personalised explanation…</div>';
  try {
    const res = await fetch("/api/advice", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: state.modelKey, inputs, supplementary, estimate,
                             nationality: state.nationality }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Advice failed");
    renderAdvice(data.advice);
  } catch (err) {
    host.innerHTML = "";
    host.append(el("p", { class: "muted" }, "Personalised advice is unavailable right now. " +
      "Your score above is still valid. " + (err.message || "")));
  }
}

function renderAdvice(a) {
  const host = $("#advice");
  host.innerHTML = "";
  const isFallback = a.source_mode === "fallback";
  host.append(el("span", { class: "ai-tag" + (isFallback ? " is-fallback" : "") },
    isFallback ? "Standard guidance" : "Personalised by Claude"));
  host.append(el("h3", {}, "What this means and what helps"));
  host.append(el("p", { class: "interpretation" }, a.interpretation || ""));

  if (Array.isArray(a.key_factors) && a.key_factors.length) {
    const kf = el("div", { class: "key-factors" });
    a.key_factors.forEach(k => kf.append(el("span", { class: "kf" }, typeof k === "string" ? k : (k.label || ""))));
    host.append(kf);
  }

  const recs = el("ol", { class: "recs" });
  (a.recommendations || []).forEach(r => {
    const li = el("li", { class: "rec" },
      el("span", { class: "rec-num" }),
      el("span", { class: "rec-action" }, r.action || ""),
      el("span", { class: "rec-why" }, (r.why || ""),
        r.source ? el("span", { class: "rec-source" }, r.source) : null));
    if (Array.isArray(r.resources) && r.resources.length) {
      const res = el("div", { class: "rec-resources" });
      r.resources.forEach(link => res.append(
        el("a", { href: link.url, target: "_blank", rel: "noopener" }, link.label + " ↗")));
      li.append(res);
    }
    if (r.resource_note) li.append(el("div", { class: "rec-note" }, r.resource_note));
    recs.append(li);
  });
  host.append(recs);

  if (a.closing_line) host.append(el("p", { class: "closing" }, a.closing_line));
}

/* ---- navigation ---- */
document.addEventListener("click", (e) => {
  const action = e.target.closest("[data-action]")?.getAttribute("data-action");
  if (action === "to-intake") showView("view-intake");
  if (action === "to-select") showView("view-select");
  if (action === "to-form") showView("view-form");
});

initTheme();
initIntake();
loadCountries();
