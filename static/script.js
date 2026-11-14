let S = null, view = "overview", charts = [], seenNotif = null, lastView = "";
const $ = (s) => document.querySelector(s);
const esc = (x) => String(x == null ? "" : x).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n) => (n == null ? "n/a" : "$" + Number(n).toLocaleString("en-US"));
const lvl = (l) => `<span class="pill ${l}">${l.toUpperCase()}</span>`;
const STATUS = { verified: "green", told: "amber", claim: "grey", none: "red", unknown: "grey" };
const fact = (s) => `<span class="pill ${STATUS[s] || "grey"}">${esc(s === "none" ? "no evidence" : s)}</span>`;
const chips = (ids) => { ids = (ids || []).filter(Boolean); return ids.length ? ids.map((i) => `<a class="ev" data-ev="${esc(i)}">${esc(i)}</a>`).join("") : `<span class="noev">Evidence unavailable</span>`; };
const rel = (s) => (s ? `<span class="pill ${{ ally: "green", warm: "green", neutral: "amber", guarded: "red" }[s] || "grey"}">${esc(s)}</span>` : `<span class="pill grey">unknown</span>`);
const acctName = (k) => ((S.accounts.find((a) => a.key === k) || {}).name || k);

const NAV = () => [["overview", "Overview"], ...S.accounts.map((a) => ["acct:" + a.key, a.name]),
  ["deals", "Deal Intelligence"], ["power", "Stakeholder Power Map"], ["actions", "Next Best Actions"], ["risks", "Risk Radar"],
  ["gaps", "Knowledge Gaps"], ["events", "Live Events"], ["notes", "Notes & Activity"], ["sources", "Data Sources / Evidence"]];

async function load() {
  try {
    const r = await fetch("/api/state");
    S = await r.json();
    if (seenNotif !== null) S.notifications.slice(seenNotif).forEach((n) => toast(n));
    seenNotif = S.notifications.length;
    render();
  } catch (e) {
    $("#banner").innerHTML = `<div class="b err">Cannot reach the AccountPulse server: ${esc(e.message)}. Showing last loaded data.</div>`;
  }
}
function toast(n) { const d = document.createElement("div"); d.className = "toast " + (n.level === "red" ? "" : "amber"); d.textContent = "New " + n.level.toUpperCase() + " risk: " + n.title; $("#toasts").appendChild(d); setTimeout(() => d.remove(), 9000); }

function render() {
  const nav = NAV();
  $("#nav").innerHTML = nav.map(([k, t]) => `<a data-v="${esc(k)}" class="${k === view ? "on" : ""}">${esc(t)}</a>`).join("");
  const sy = S.sync, title = (nav.find((n) => n[0] === view) || ["", "Overview"])[1];
  $("#top").innerHTML = `<h1>${esc(title)}</h1><div class="sync">Last successful sync: <b>${esc(sy.last_success || "never")}</b><br>API calls this session: ${sy.calls}${sy.busy ? " | fetching " + esc(sy.busy) + "..." : sy.next_call_in != null ? " | next call in " + sy.next_call_in + "s (" + esc(sy.next_job || "-") + ")" : ""}</div>`;
  let b = "";
  if (!sy.token_set) b += `<div class="b err"><b>Setup needed:</b> AQ_TOKEN is not set on the server. Add it as an environment variable and restart. No data is shown until the live API is reached.</div>`;
  if (sy.errors.length) { const e = sy.errors[sy.errors.length - 1]; b += `<div class="b warn">Last API error (${esc(e.tool)} at ${esc(e.at)}): ${esc(e.error)}. Cached data is preserved.</div>`; }
  if (sy.token_set && !S.has_data) b += `<div class="b info">Loading your accounts from the Questathon API (1 call per minute). This page refreshes automatically.</div>`;
  $("#banner").innerHTML = b;
  charts.forEach((c) => c.destroy()); charts = [];
  const v = $("#view");
  if (!S.has_data && view !== "sources") { v.innerHTML = `<div class="card"><h2>Waiting for data</h2><p class="muted">No customer data has been fetched yet. Nothing is shown rather than showing made-up data. See Data Sources for sync status.</p></div>`; if (view === "overview") return; }
  const fn = { overview: vOverview, deals: () => vDeals(), power: () => vPower(), actions: () => vActions(), risks: () => vRisks(), gaps: () => vGaps(), events: vEvents, notes: vNotes, sources: vSources };
  if (view.startsWith("acct:")) v.innerHTML = vAccount(view.slice(5));
  else if (S.has_data || view === "sources") v.innerHTML = (fn[view] || vOverview)();
  if (view === "overview" && S.has_data) drawCharts();
  if (view === "notes") bindNotes();
}

function vOverview() {
  const tot = S.accounts.filter((a) => !a.extra).reduce((t, a) => { t.v += a.totals.verified; t.b += a.totals.blocked; t.q += a.totals.qualified_unverified; t.u += a.totals.uncertain; return t; }, { v: 0, b: 0, q: 0, u: 0 });
  const reds = S.accounts.filter((a) => !a.extra).flatMap((a) => a.risks).filter((r) => r.level === "red");
  return `<div class="grid g4">
  <div class="card kpi"><div class="n">${usd(tot.v)}</div><div class="l">Qualified, verified evidence, no open blocker (up to)</div></div>
  <div class="card kpi"><div class="n">${usd(tot.b)}</div><div class="l">Qualified, verified evidence but blocker OPEN (up to)</div></div>
  <div class="card kpi"><div class="n">${usd(tot.q)}</div><div class="l">Qualified ceiling, no verified evidence (up to)</div></div>
  <div class="card kpi"><div class="n">${usd(tot.u)}</div><div class="l">Non-qualified ceilings (up to)</div></div>
  <div class="card kpi"><div class="n">${reds.length}</div><div class="l">RED risks open</div></div></div>
  <div class="card"><h2>Reconciliation with the morning snapshot</h2><p>Reported book: <b>${usd(S.snapshot_total)}</b> (morning snapshot, not API; not treated as verified). Snapshot figures matched to API deals: <b>${usd(S.snapshot_matched)}</b>. The API gives only a <b>ceiling ("worth up to")</b> for qualified deals and nothing for identified deals, so the reported book cannot be confirmed to the dollar from the API. API ceilings total <b>${usd(S.api_total_with_value)}</b> and are shown separately from the snapshot figures. Evidence on a deal is the list the API attaches to it; it supports qualification, not a price.</p></div>
  <div class="grid g2"><div class="card"><h2>Deal ceilings by evidence quality</h2><div class="chart"><canvas id="c1"></canvas></div></div><div class="card"><h2>Risks by level</h2><div class="chart"><canvas id="c2"></canvas></div></div></div>
  <div class="card"><h2>Top RED risks</h2>${reds.slice(0, 5).map(riskHtml).join("") || '<span class="muted">No red risks.</span>'}</div>`;
}
function drawCharts() {
  if (!window.Chart) return;
  charts.push(new Chart($("#c1"), { type: "bar", data: { labels: S.accounts.map((a) => a.name), datasets: [{ label: "Verified, unblocked", data: S.accounts.map((a) => a.totals.verified), backgroundColor: "#12a150" }, { label: "Verified, blocker open", data: S.accounts.map((a) => a.totals.blocked), backgroundColor: "#65a30d" }, { label: "Qualified, unverified", data: S.accounts.map((a) => a.totals.qualified_unverified), backgroundColor: "#d97706" }, { label: "Uncertain", data: S.accounts.map((a) => a.totals.uncertain), backgroundColor: "#98a2b3" }] }, options: { maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true } } } }));
  const c = { red: 0, amber: 0, green: 0 }; S.accounts.forEach((a) => a.risks.forEach((r) => c[r.level]++));
  charts.push(new Chart($("#c2"), { type: "doughnut", data: { labels: ["Red", "Amber", "Green"], datasets: [{ data: [c.red, c.amber, c.green], backgroundColor: ["#d92d20", "#d97706", "#12a150"] }] }, options: { maintainAspectRatio: false } }));
}

function dealRows(ds) {
  return `<table><tr><th>Deal</th><th>Stage</th><th>Value (API ceiling)</th><th>Counted as</th><th>Best evidence</th><th>Evidence on the deal (status)</th><th>Supporting person / file</th><th>Morning snapshot</th></tr>${ds.map((d) => {
    const cl = { qualified_verified: ["green", "Qualified, verified, no open blocker"], qualified_blocked: ["amber", "Qualified, verified evidence, BLOCKER OPEN"], qualified_unverified: ["amber", "Qualified, NOT verified"], uncertain: ["red", "Not qualified / uncertain"], no_value: ["grey", "No value in API"] }[d.counted];
    const sn = d.snapshot ? `${d.snapshot.value == null ? "no value" : usd(d.snapshot.value)} / ${esc(d.snapshot.stage)}${d.worth != null && d.snapshot.value != null && d.snapshot.value > d.worth ? ' <span class="pill red">above ceiling</span>' : ""}` : '<span class="muted">-</span>';
    const ev = d.detail.length ? d.detail.map((e) => `${chips([e.id])}${fact(e.kind === "file" ? "verified" : e.status)}`).join("<br>") : '<span class="noev">Evidence unavailable</span>';
    return `<tr><td><b>${esc(d.name)}</b><br>${chips([d.id])}</td><td>${esc(d.stage)}</td><td>${d.worth == null ? '<span class="muted">no value in API</span>' : "up to " + usd(d.worth) + "<br>" + chips([d.id])}</td><td><span class="pill ${cl[0]}">${cl[1]}</span></td><td>${fact(d.backing)}</td><td>${ev}</td><td>${d.support.length ? esc(d.support.join(", ")) : '<span class="noev">none linked</span>'}</td><td>${sn}${d.snapshot ? '<br><span class="muted">morning snapshot, not API</span>' : ""}</td></tr>`;
  }).join("")}</table>`;
}
function offersTable(a) {
  if (!a.offers || !a.offers.length) return "";
  return `<h3>Offers pitched (not deals, not counted in the book)</h3><table><tr><th>Offer</th><th>Value</th><th>Pitched to</th><th>Status</th><th>ID</th></tr>${a.offers.map((o) => `<tr><td>${esc(o.title)}</td><td>${usd(o.value)}</td><td>${esc(o.pitch_to)}</td><td>${esc(o.status)}</td><td>${chips([o.id])}</td></tr>`).join("")}</table>`;
}
const sel = (key) => S.accounts.filter((a) => !key || a.key === key);
function vDeals(key) {
  return sel(key).map((a) => `<div class="card"><h2>${esc(a.name)} - What is the book worth?</h2><p>Ceilings ("up to"): verified and unblocked <b>${usd(a.totals.verified)}</b> | verified but blocker open <b>${usd(a.totals.blocked)}</b> | qualified, no verified evidence <b>${usd(a.totals.qualified_unverified)}</b> | not qualified (kept separate) <b>${usd(a.totals.uncertain)}</b></p>${dealRows(a.deals)}${offersTable(a)}<p class="muted">Rules: only qualified/cleared/agreed deals with a value count as qualified. \"Verified\" needs a verified fact or a file among the deal's evidence; a claim or \"told\" never counts as verified. The API value is a ceiling, not a booked amount.</p></div>`).join("");
}
function vPower(key) {
  return sel(key).map((a) => `<div class="card"><h2>${esc(a.name)} - Who holds the power?</h2><table><tr><th>Deal</th>${["Decision-maker", "Payer", "End user", "Blocker", "Champion"].map((h) => `<th>${h}</th>`).join("")}<th>Evidence</th></tr>${a.power.map((p) => `<tr><td><b>${esc(p.deal)}</b><br><span class="muted">${esc(p.stage)}</span></td>${["decision_maker", "payer", "end_user", "blocker", "champion"].map((r) => { const x = p.roles[r]; return `<td>${x ? esc(x.name) + (x.is_person ? "<br>" + rel(x.status) + (x.available === false ? ' <span class="pill red">unavailable</span>' : "") : "") + (x.src ? '<br><span class="muted">' + esc(x.src) + "</span>" : "") : '<span class="pill grey">Unknown</span>'}</td>`; }).join("")}<td>${chips(p.evidence)}</td></tr>`).join("")}</table>
  <h3>People met / known</h3><table><tr><th>Name</th><th>Role</th><th>Status</th><th>ID</th></tr>${a.people.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.role)}</td><td>${rel(p.status === "unknown" ? "" : p.status)}${p.available === false ? " <span class=\"pill red\">unavailable</span>" : ""}</td><td>${chips([p.id])}</td></tr>`).join("")}</table></div>`).join("");
}
function actHtml(x) {
  return `<tr><td><b>#${x.rank}</b></td><td>${esc(x.action)}<br><span class="muted">${esc(x.reason)}</span></td><td>${esc(x.owner)}</td><td>${esc(x.due)}</td><td>${esc(x.deal)}</td><td>${esc(x.probability)}</td><td>${chips(x.evidence)}</td><td><button class="btn s" data-save="${esc(x.id)}">Write to notes</button></td></tr>`;
}
function vActions(key) {
  return sel(key).map((a) => `<div class="card"><h2>${esc(a.name)} - Top three actions</h2><table><tr><th>Rank</th><th>Action</th><th>Owner</th><th>Due</th><th>Deal</th><th>Probability</th><th>Evidence</th><th></th></tr>${a.actions.filter((x) => x.top).map(actHtml).join("") || '<tr><td colspan=8 class="muted">No actions derivable yet.</td></tr>'}</table><p class="muted">Ranking: deal value + stage + deadline urgency + blockers + relationship coldness; live events outrank routine deals. Owners and dates are never invented: "Unassigned" / "Requires confirmation" means the data does not say.</p>${a.actions.length > 3 ? `<details><summary>Remaining ${a.actions.length - 3} candidates</summary><table>${a.actions.filter((x) => !x.top).map(actHtml).join("")}</table></details>` : ""}</div>`).join("");
}
function riskHtml(r) { return `<div class="risk ${r.level}">${lvl(r.level)} <b>${esc(r.title)}</b> <span class="muted">(${esc(r.kind || "")}${r.account ? " | " + esc(acctName(r.account)) : ""})</span><br>${esc(r.reason)}<br><span class="muted">Impact: ${esc(r.impact)}</span><br>${chips(r.evidence)}</div>`; }
function vRisks(key) { return sel(key).map((a) => `<div class="card"><h2>${esc(a.name)} - What is about to go wrong?</h2>${a.risks.map(riskHtml).join("") || '<span class="muted">No risks derived.</span>'}</div>`).join(""); }
function vGaps(key) {
  return sel(key).map((a) => `<div class="card"><h2>${esc(a.name)} - What do we still not know?</h2><table><tr><th>Priority</th><th>Missing</th><th>Why it matters</th><th>Deal</th><th>Who could answer</th><th>Question to ask</th><th>Evidence</th></tr>${a.gaps.map((g) => `<tr><td>${lvl({ High: "red", Medium: "amber", Low: "green" }[g.priority] || "amber").replace(/RED|AMBER|GREEN/, g.priority.toUpperCase())}</td><td>${esc(g.missing)}</td><td>${esc(g.why)}</td><td>${esc(g.deal)}</td><td>${esc(g.who)}</td><td>${esc(g.ask)}</td><td>${chips(g.evidence)}</td></tr>`).join("") || '<tr><td colspan=7 class="muted">None derived.</td></tr>'}</table></div>`).join("");
}
function vAccount(key) {
  const a = S.accounts.find((x) => x.key === key); if (!a) return "";
  return `<div class="card"><h2>${esc(a.name)}</h2>${a.official ? `<p class="muted">Official story (unverified): ${esc(a.official)}</p>` : ""}<p>${a.people.length} people, ${a.deals.length} deals, ${a.files.length} files, ${a.facts.length} facts.</p></div>` + vDeals(key) + vPower(key) + vActions(key) + vRisks(key) + vGaps(key);
}
function vEvents() {
  return `<div class="card"><h2>Live events detected via get_signals</h2><p class="muted">Polled automatically (1 call/min shared with other reads). New events create risks, notifications and actions without any code change.</p><table><tr><th>Detected</th><th>Account</th><th>Event</th><th>Detail</th><th>Evidence</th></tr>${S.events.slice().reverse().map((e) => `<tr><td>${esc(e.detected_at)}</td><td>${esc(e.account ? acctName(e.account) : "unmatched")}</td><td><b>${esc(e.title)}</b><br><span class="muted">${esc(e.when)}</span></td><td>${esc(e.detail)}</td><td>${chips([e.id || "signal:" + e.uid])}</td></tr>`).join("") || '<tr><td colspan=5 class="muted">No events fetched yet.</td></tr>'}</table></div>
  <div class="card"><h2>Notifications</h2>${S.notifications.slice().reverse().map((n) => `<div class="risk ${n.level}">${lvl(n.level)} ${esc(n.title)} <span class="muted">${esc(n.at)}</span></div>`).join("") || '<span class="muted">None yet.</span>'}</div>`;
}
function vNotes() {
  return `<div class="card"><h2>Write a note / task / risk / next step (write_note)</h2><select id="na"><option value="">No account</option>${S.accounts.map((a) => `<option value="${esc(a.key)}">${esc(a.name)} (${esc(a.key)})</option>`).join("")}</select><select id="nk"><option>note</option><option>task</option><option>risk</option><option>next_step</option></select><input id="nt" placeholder="Title (optional)"><textarea id="nx" rows="3" placeholder="Text"></textarea><button class="btn" id="ns">Save note</button> <span id="nm" class="muted"></span><p class="muted">Notes are queued and sent on the next free API slot (1 call/min).</p></div>
  <div class="card"><h2>Notes & activity</h2><table><tr><th>When</th><th>Account</th><th>Kind</th><th>Text</th><th>Status</th></tr>${S.notes.slice().reverse().map((n) => `<tr><td>${esc(n.created)}</td><td>${esc(n.account || "-")}</td><td>${esc(n.kind)}</td><td>${esc(n.title ? n.title + ": " : "")}${esc(n.text)}</td><td><span class="pill ${{ saved: "green", pending: "amber", failed: "red" }[n.status]}">${esc(n.status)}</span>${n.error ? `<br><span class="muted">${esc(n.error)}</span>` : ""}</td></tr>`).join("") || '<tr><td colspan=5 class="muted">No notes yet.</td></tr>'}</table></div>`;
}
function bindNotes() {
  $("#ns").onclick = async () => { const text = $("#nx").value.trim(); if (!text) { $("#nm").textContent = "Enter text."; return; } const r = await fetch("/api/notes", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text, account: $("#na").value, kind: $("#nk").value, title: $("#nt").value }) }); $("#nm").textContent = r.ok ? "Queued." : "Failed."; load(); };
}
function vSources() {
  const sy = S.sync;
  return `<div class="card"><h2>Sync status</h2><p>Token configured: <b>${sy.token_set ? "yes" : "NO"}</b> | Calls this session: ${sy.calls} | Last success: ${esc(sy.last_success || "never")} | Paperwork cached for accounts: ${esc(S.paperwork_loaded.join(", ") || "none yet")} | Signals loaded: ${S.signals_loaded ? "yes" : "no"} | Evidence ids indexed: ${S.evidence_count}</p>
  <table><tr><th>When</th><th>Tool</th><th>Result</th></tr>${sy.log.slice().reverse().map((l) => `<tr><td>${esc(l.at)}</td><td>${esc(l.tool)} ${esc(JSON.stringify(l.args || {}))}</td><td>${l.ok ? '<span class="pill green">ok</span>' : '<span class="pill red">error</span> ' + esc(l.error)}</td></tr>`).join("") || '<tr><td colspan=3 class="muted">No calls yet.</td></tr>'}</table></div>
  <div class="card"><h2>Data Check</h2><p class="muted">Raw shape of what the Questathon API returned, so you can verify the real response.</p><button class="btn" id="dc">Load data check</button><pre id="dcout" class="hidden"></pre></div>
  <div class="card"><h2>Evidence lookup</h2><p class="muted">Click any evidence ID anywhere. Fact status: claim (may be wrong), told (a person said it), verified (backed by a file).</p><p>${S.evidence_ids.slice(0, 120).map((i) => chips([i])).join("")}</p></div>`;
}

async function showEv(id) {
  $("#modal").classList.remove("hidden"); $("#mbody").innerHTML = "Loading...";
  const r = await fetch("/api/evidence/" + encodeURIComponent(id));
  const e = await r.json();
  $("#mbody").innerHTML = r.ok ? `<h2>${esc(e.id)}</h2><p>Type: <b>${esc(e.type)}</b>${e.account ? " | Account: " + esc(e.account) : ""}${e.status ? " | Status: " + fact(e.status) : ""}${e.person ? "<br>Person: " + esc(e.person) : ""}${e.source ? "<br>Source file: " + esc(e.source) : ""}</p><pre>${esc(e.record)}</pre>` : `<h2>${esc(id)}</h2><p>Evidence unavailable: this id was not found in the cached API data.</p>`;
}
function closeModal() { $("#modal").classList.add("hidden"); }

document.addEventListener("click", async (e) => {
  const t = e.target;
  if (t.dataset.ev) showEv(t.dataset.ev);
  if (t.dataset.v) { view = t.dataset.v; render(); window.scrollTo(0, 0); }
  if (t.dataset.save) {
    const x = S.accounts.flatMap((a) => a.actions).find((z) => z.id === t.dataset.save);
    if (x) { await fetch("/api/notes", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: x.action + " | Owner: " + x.owner + " | Due: " + x.due + " | Evidence: " + (x.evidence || []).join(", "), account: x.account, kind: "next_step", title: "Rank " + x.rank }) }); t.textContent = "Queued"; t.disabled = true; }
  }
  if (t.id === "dc") { const r = await fetch("/api/datacheck"); const o = $("#dcout"); o.textContent = JSON.stringify(await r.json(), null, 2); o.classList.remove("hidden"); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
load();
setInterval(() => { if (document.activeElement && ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return; load(); }, 20000);
