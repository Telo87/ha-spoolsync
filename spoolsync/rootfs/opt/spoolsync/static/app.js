"use strict";

const $ = (sel) => document.querySelector(sel);
let state = null;
let busy = false;

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function when(ts) {
  if (!ts) return "–";
  const d = new Date(ts * 1000);
  const today = new Date().toDateString() === d.toDateString();
  return today
    ? d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4000);
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `Fehler ${resp.status}`);
  return data;
}

function renderSpoolman(s) {
  const err = s.spoolman.error ? `<div class="err-box">${esc(s.spoolman.error)}</div>` : "";
  $("#sm-body").innerHTML = `${err}<dl class="kv">
    <dt>Adresse</dt><dd>${esc(s.spoolman.url)}</dd>
    <dt>Spulen</dt><dd>${s.spoolman.error ? "–" : s.spoolman.count + " aktiv"}</dd></dl>
    <p class="hint">Die Adresse wird in der Konfiguration des Add-ons eingestellt.</p>`;
}

function renderBambu(s) {
  const b = s.bambu;
  const err = b.error && b.signed_in ? `<div class="err-box">${esc(b.error)}</div>` : "";
  if (b.signed_in) {
    $("#bb-body").innerHTML = `${err}<dl class="kv">
      <dt>Konto</dt><dd>${esc(b.email)} <span class="pill ok">angemeldet</span></dd>
      <dt>Spulen</dt><dd>${b.error ? "–" : b.count + " aktiv"}</dd></dl>
      <button class="link" id="logout">Abmelden</button>`;
    $("#logout").onclick = () => act(() => api("api/logout", {}), "Abgemeldet");
  } else if (b.pending) {
    $("#bb-body").innerHTML = b.pending === "tfa"
      ? "Bitte den Code aus der Authenticator-App eingeben."
      : "Bambu Lab hat einen Code an die E-Mail-Adresse geschickt.";
  } else {
    $("#bb-body").innerHTML = b.error && !b.error.startsWith("Nicht bei")
      ? `<div class="err-box">${esc(b.error)}</div>` : "Noch nicht angemeldet.";
  }
  $("#login").hidden = b.signed_in || !!b.pending;
  $("#code").hidden = b.signed_in || !b.pending;
  $("#resend").hidden = b.pending !== "code";
  $("#code-label").textContent = b.pending === "tfa" ? "Code der Authenticator-App" : "Code aus der E-Mail";
}

function renderSync(s) {
  const n = s.plan.length;
  const mode = s.auto_sync
    ? `<span class="pill ok">automatisch</span> alle ${s.interval_minutes} min`
    : `<span class="pill info">Probelauf</span> – übernommen wird nur per Knopf`;
  $("#sync-body").innerHTML = `<dl class="kv">
    <dt>Modus</dt><dd>${mode}</dd>
    <dt>Geprüft</dt><dd>${when(s.last_check)}</dd>
    <dt>Abgeglichen</dt><dd>${when(s.last_sync)}</dd>
    <dt>Vorrang</dt><dd>${s.conflict_winner === "bambu" ? "Bambu-Cloud" : "Spoolman"}
      <span class="muted">(Restgewicht: der kleinere Wert)</span></dd>
    <dt>Löschen</dt><dd>${s.sync_deletions ? "wird übernommen" : "wird nicht übernommen"}</dd></dl>`;
  const ready = !s.spoolman.error && s.bambu.signed_in && !s.bambu.error;
  const btn = $("#btn-sync");
  btn.disabled = busy || s.busy || !ready || n === 0;
  btn.textContent = n ? `Jetzt abgleichen (${n} ${n === 1 ? "Änderung" : "Änderungen"})` : "Alles gleich";
  $("#btn-check").disabled = busy || s.busy;
}

function renderPlan(s) {
  $("#warnings").innerHTML = s.warnings.map((w) => `<div class="warn-box">${esc(w)}</div>`).join("");
  const ready = !s.spoolman.error && s.bambu.signed_in && !s.bambu.error;
  $("#plan").innerHTML = !ready
    ? `<li class="muted">Erst wenn beide Seiten erreichbar sind, lässt sich vergleichen.</li>`
    : s.plan.length
      ? s.plan.map((a) => `<li>${esc(a.text)}</li>`).join("")
      : `<li class="muted">Keine Änderungen nötig – beide Seiten zeigen dieselben Spulen.</li>`;
}

function side(x) {
  if (!x) return `<span class="muted">fehlt</span>`;
  const pct = x.total_raw ? Math.max(0, Math.min(100, Math.round(100 * x.remaining_raw / x.total_raw))) : null;
  const extra = [x.material, x.slot ? `im Drucker (${x.slot})` : "", x.location, x.archived ? "archiviert" : ""]
    .filter(Boolean).map(esc).join(" · ");
  return `<div class="side"><div class="t">${esc(x.vendor !== "–" ? x.vendor + " " : "")}${esc(x.name !== "–" ? x.name : x.material)}</div>
    <div class="w">${esc(x.remaining_g)} von ${esc(x.total_g)}${pct !== null ? ` (${pct} %)` : ""}${extra ? " · " + extra : ""}</div>
    ${pct !== null ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}</div>`;
}

function rowState(r) {
  if (!r.sm) return `<span class="pill warn">nur Bambu-Cloud</span>`;
  if (!r.bb) return `<span class="pill warn">nur Spoolman</span>`;
  const keys = ["vendor", "material", "name", "color", "total_g", "remaining_g", "note"];
  const diff = keys.filter((k) => String(r.sm[k]).toLowerCase() !== String(r.bb[k]).toLowerCase());
  return diff.length ? `<span class="pill info">weicht ab</span>` : `<span class="pill ok">gleich</span>`;
}

function renderSpools(s) {
  const rows = s.rows;
  $("#spools tbody").innerHTML = rows.length ? rows.map((r) => {
    const color = (r.sm && r.sm.color) || (r.bb && r.bb.color);
    return `<tr><td class="sw">${color ? `<span class="swatch" style="background:#${esc(color)}"></span>` : ""}</td>
      <td data-label="Spoolman">${side(r.sm)}</td>
      <td data-label="Bambu-Cloud">${side(r.bb)}</td>
      <td>${rowState(r)}</td></tr>`;
  }).join("") : `<tr><td colspan="4" class="muted">Noch keine Spulen gelesen.</td></tr>`;
}

function renderLog(s) {
  $("#log").innerHTML = s.log.length
    ? s.log.map((e) => `<li class="${e.level === "error" ? "error" : ""}"><span class="time">${when(e.t)}</span>${esc(e.text)}</li>`).join("")
    : `<li class="muted">Noch nichts übernommen.</li>`;
}

function render(s) {
  state = s;
  $("#demo").hidden = !s.demo;
  renderSpoolman(s);
  renderBambu(s);
  renderSync(s);
  renderPlan(s);
  renderSpools(s);
  renderLog(s);
}

async function act(fn, okText) {
  busy = true;
  if (state) renderSync(state);
  try {
    const data = await fn();
    if (data && data.rows) render(data);
    if (okText) toast(typeof okText === "function" ? okText(data) : okText);
    return data;
  } catch (err) {
    toast(err.message);
  } finally {
    busy = false;
    if (state) renderSync(state);
  }
}

async function load() {
  try { render(await api("api/state")); } catch (err) { toast(err.message); }
}

$("#login").onsubmit = (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  act(() => api("api/login", { email: f.get("email"), password: f.get("password"), region: f.get("region") }),
    (d) => (d.status === "ok" ? "Angemeldet" : "Bitte den Code eingeben"));
  ev.target.password.value = "";
};
$("#code").onsubmit = (ev) => {
  ev.preventDefault();
  act(() => api("api/code", { code: new FormData(ev.target).get("code") }), "Angemeldet");
  ev.target.reset();
};
$("#resend").onclick = () => act(() => api("api/resend", {}), "Neuer Code verschickt");
$("#btn-check").onclick = () => act(() => api("api/check", {}), "Geprüft");
$("#btn-sync").onclick = () => act(() => api("api/sync", {}), (d) => {
  const r = d.result || {};
  return r.failed ? `${r.done} übernommen, ${r.failed} fehlgeschlagen – siehe Verlauf` : `${r.done} Änderungen übernommen`;
});

load();
setInterval(() => { if (!busy) load(); }, 15000);
