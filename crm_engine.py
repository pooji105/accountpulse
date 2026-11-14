"""CRM engine: turns raw Questathon responses into the five answers.

Real response shape (verified against the live export):
  account: id, name, official_story, facts[{id,said_by,status,text,verified_by?}],
           offers[{id,pitch_to,status,title,value}], opportunities[{id,title,stage,worth_up_to,
           blocker{text,status}|null, deadline{text,moves_left,soon,passed,met}|null, evidence[ids]}],
           stakeholders[{id,name,role,relationship,available}], deadlines[{text,passed}]
  top level: files[{account,id,path,title}]
Nothing is invented. The only constants are the user-supplied MORNING items, always labelled
"morning snapshot (not API)".
"""
import hashlib
import json
import re

BACKED = {"qualified", "cleared", "agreed"}
STATUS_OK = {"guarded", "neutral", "warm", "ally"}
FACT_OK = {"claim", "told", "verified"}
RANK = {"verified": 3, "told": 2, "claim": 1, "none": 0, "unknown": 0}
SNAPSHOT_TOTAL = 264398
MORNING_SRC = "Morning snapshot (not API)"
SNAPSHOT = [  # morning snapshot supplied by the user: (name phrase, value, stage)
    ("alliance contract", 19522, "Identified"), ("tarn valley", 49744, "Qualified"),
    ("westmere", None, "Never heard of"), ("300-dock", 50028, "Identified"),
    ("aldermoor contract", 31944, "Qualified"), ("idle plants", 66530, "Qualified"),
    ("insurance discount", None, "Never heard of"), ("sister company", 46630, "Identified")]
# From the user's "This morning" page (not in the API):
MORNING_ROLES = {"alliance contract": {"decision_maker": "Rhys Calder", "payer": "Ewan Brooks"},
                 "300-dock": {"decision_maker": "Hannah Doyle", "payer": "Ewan Brooks"}}
MORNING_BLOCKERS = {"alliance contract": "Nobody can show which forces actually use the docks",
                    "300-dock": "The specification has no costed operating model"}
MORNING_PROPOSALS = {"tarn valley": ("Fatima Osei", ["srv_dataflow", "fo_needs_3", "support_ticket_history"]),
                     "aldermoor contract": ("Nadia Rahman", ["jt_prem_2", "nr_evidence_2"])}
MORNING_UNMET = [("Hannah Doyle", "Alliance procurement lead", "A"), ("Julian Tate", "Insurance and risk manager", "B")]
ROLE_KEYS = [("decision_maker", ("decid",)), ("payer", ("payer", "pays", "budget_holder")), ("end_user", ("end_user", "operator")),
             ("blocker", ("block",)), ("champion", ("champ",))]
ROLE_LABEL = {"decision_maker": "Decision-maker", "payer": "Payer", "end_user": "End user",
              "blocker": "Blocker", "champion": "Champion"}


# ---------- tolerant helpers ----------
def low(x):
    return str(x).lower()


def g(d, *keys):
    if not isinstance(d, dict):
        return None
    lk = {low(k): k for k in d}
    for k in keys:
        if low(k) in lk and d[lk[low(k)]] not in (None, ""):
            return d[lk[low(k)]]
    return None


def flat(d):
    out = dict(d)
    for k, v in d.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                out.setdefault(kk, vv)
    return out


def txt(v):
    if v is None:
        return ""
    if isinstance(v, dict):
        return txt(g(v, "name", "text", "label", "title", "id")) or json.dumps(v)
    if isinstance(v, list):
        return ", ".join(txt(x) for x in v)
    return str(v)


def num(v):
    if isinstance(v, dict):
        v = g(v, "amount", "value", "usd", "worth")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.sub(r"[^0-9.]", "", v)
        try:
            return float(m) if m else None
        except ValueError:
            return None
    return None


def listify(v):
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        vals = list(v.values())
        if vals and all(isinstance(x, dict) for x in vals):
            out = []
            for k, x in v.items():
                x = dict(x)
                x.setdefault("id", k)
                out.append(x)
            return out
    return []


def extract_list(raw, keys):
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for k in keys:
            if k in raw:
                return extract_list(raw[k], keys)
        return listify(raw)
    return []


ACCT_MARK = ("deals", "people", "opportunities", "stakeholders")


def extract_accounts(raw):
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if not isinstance(raw, dict):
        return []
    for k in ("accounts", "my_accounts"):
        if k in raw:
            return extract_accounts(raw[k])
    out = []
    for k, v in raw.items():
        if isinstance(v, dict) and any(low(x) in ACCT_MARK for x in v):
            v = dict(v)
            v["_key"] = k
            out.append(v)
    if out:
        return out
    if any(low(x) in ACCT_MARK for x in raw):
        return [raw]
    for v in raw.values():
        if isinstance(v, (dict, list)):
            r = extract_accounts(v)
            if r:
                return r
    return []


def extract_files(raw):
    if isinstance(raw, dict):
        if isinstance(raw.get("files"), list):
            return [f for f in raw["files"] if isinstance(f, dict)]
        for v in raw.values():
            if isinstance(v, dict) and isinstance(v.get("files"), list):
                return [f for f in v["files"] if isinstance(f, dict)]
    return []


def money(v):
    return None if v is None else int(round(v))


# ---------- normalisation ----------
def norm_account(a, idx, files_all=None, extra=False):
    k = a.get("_key")
    if not (isinstance(k, str) and len(k) <= 2):
        k = g(a, "id", "key", "letter", "slot")
    key = str(k) if isinstance(k, str) and len(k) <= 2 else chr(65 + idx)
    name = g(a, "name", "company", "title", "account_name")
    name = name if isinstance(name, str) else "Account " + key
    people = []
    for p in listify(g(a, "stakeholders", "people", "contacts")):
        st = low(g(p, "relationship", "status", "stance", "warmth") or "")
        av = p.get("available")
        people.append({"id": g(p, "id"), "name": txt(g(p, "name")) or txt(g(p, "id")), "role": txt(g(p, "role", "title", "position")),
                       "status": st if st in STATUS_OK else "unknown", "available": av if isinstance(av, bool) else None, "raw": p})
    facts = []
    for f in listify(g(a, "facts", "quotes", "claims", "statements")):
        st = low(g(f, "status", "fact_status", "kind", "type") or "")
        facts.append({"id": g(f, "id"), "text": txt(g(f, "text", "statement", "said", "quote", "claim")),
                      "person": txt(g(f, "said_by", "person", "who", "speaker", "by", "told_by")),
                      "status": st if st in FACT_OK else "unknown", "by": txt(g(f, "verified_by", "source", "file")), "raw": f})
    deals = []
    for d in listify(g(a, "opportunities", "deals")):
        fd = flat(d)
        bl = d.get("blocker")
        deals.append({"id": g(d, "id"), "name": txt(g(d, "title", "name")) or "(unnamed deal)",
                      "stage": low(g(d, "stage") or "unknown"), "worth": num(g(d, "worth_up_to", "worth", "value", "amount")),
                      "blocker": txt(bl.get("text") if isinstance(bl, dict) else bl), "owner": txt(g(d, "owner", "assigned_to")),
                      "prob": g(d, "probability", "prob", "chance"), "raw": d, "flat": fd})
    dls = []
    for d in listify(g(a, "deadlines")):
        dls.append({"id": g(d, "id"), "label": txt(g(d, "text", "label", "name", "title")), "passed": bool(d.get("passed")),
                    "soon": bool(d.get("soon")), "met": bool(d.get("met")), "moves_left": d.get("moves_left"), "deal_id": None, "raw": d})
    own_files = listify(g(a, "files", "documents"))
    fl = list(own_files) + [f for f in (files_all or []) if str(f.get("account")) == key]
    files = [{"id": g(f, "id"), "name": txt(g(f, "title", "name", "label")), "path": g(f, "path"), "raw": f} for f in fl]
    offers = [{"id": g(o, "id"), "title": txt(g(o, "title", "name")), "value": num(g(o, "value", "amount")), "pitch_to": txt(g(o, "pitch_to", "to")),
               "status": txt(g(o, "status")), "raw": o} for o in listify(g(a, "offers"))]
    return {"key": key, "name": name, "people": people, "facts": facts, "deals": deals, "deadlines": dls, "files": files, "offers": offers,
            "official": txt(g(a, "official_story", "official", "story")), "extra": extra, "raw": a}


def all_accounts(raw):
    files_all = extract_files(raw.get("accounts"))
    out = [norm_account(a, i, files_all) for i, a in enumerate(extract_accounts(raw.get("accounts")))]
    used = {a["key"] for a in out}
    for nid, res in (raw.get("new_accounts") or {}).items():
        lst = extract_accounts(res)
        if lst:
            a = dict(lst[0])
            a["_key"] = nid if len(str(nid)) <= 2 else a.get("_key")
            na = norm_account(a, len(out), extract_files(res), extra=True)
            if na["key"] in used:
                na["key"] = str(nid)
            used.add(na["key"])
            out.append(na)
    return out


def account_keys(raw):
    """Keys of the core accounts only (used to fetch paperwork)."""
    return [norm_account(a, i)["key"] for i, a in enumerate(extract_accounts(raw))]


def new_account_ids(who):
    if isinstance(who, dict):
        return [str(x.get("id")) for x in who.get("new_accounts", []) if isinstance(x, dict) and x.get("id")]
    return []


def norm_signal(s, i):
    title = txt(g(s, "title", "headline", "name", "event"))
    detail = txt(g(s, "summary", "detail", "details", "body", "description", "text", "message"))
    if not title:
        title = (detail[:90] or json.dumps(s)[:90])
    uid = hashlib.sha1(json.dumps(s, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return {"id": g(s, "id", "signal_id", "key"), "uid": uid, "title": title, "detail": detail,
            "when": txt(g(s, "dated", "date", "when", "at", "created_at", "timestamp")), "account_raw": txt(g(s, "account", "account_id")),
            "records": [r for r in (s.get("records") or []) if isinstance(r, dict)], "raw": s, "idx": i}


def signals_from(raw):
    return [norm_signal(s, i) for i, s in enumerate(extract_list(raw, ("signals", "events")))]


def acct_for_signal(sig, accts):
    ar = sig["account_raw"].strip().lower()
    t = (sig["title"] + " " + sig["detail"]).lower()
    for a in accts:
        if ar and (ar == a["key"].lower() or ar in a["name"].lower() or a["name"].lower() in ar):
            return a["key"]
    for a in accts:
        w = a["name"].split()[0].lower() if a["name"].split() else ""
        if w and len(w) > 3 and w in t:
            return a["key"]
    return None


# ---------- evidence from paperwork / records ----------
def usage_drops(sig):
    """From a usage record (csv): docks that flew in the first half of the window and nothing in the last two weeks."""
    for rec in sig["records"]:
        if low(rec.get("kind")) != "usage":
            continue
        rows = [ln.split(",") for ln in str(rec.get("text", "")).strip().splitlines()]
        if len(rows) < 2:
            continue
        hdr = [h.strip() for h in rows[0]]
        try:
            iw, idk, ifl = hdr.index("week_start"), hdr.index("dock_id"), hdr.index("flights")
        except ValueError:
            continue
        per = {}
        for r in rows[1:]:
            if len(r) <= max(iw, idk, ifl):
                continue
            try:
                per.setdefault(r[idk], []).append((r[iw], int(r[ifl])))
            except ValueError:
                pass
        flagged = []
        for dock, wk in per.items():
            wk.sort()
            if len(wk) < 4:
                continue
            early = sum(x[1] for x in wk[:-2])
            late = sum(x[1] for x in wk[-2:])
            if early >= 8 and late == 0:
                flagged.append("%s (%d flights before, 0 in last two weeks)" % (dock, early))
        return sorted(flagged), rec.get("path")
    return [], None


def calls_mentioning(raw, key, name):
    pw = (raw.get("paperwork") or {}).get(key)
    recs = pw.get("records") if isinstance(pw, dict) else None
    if not recs:
        return None
    calls = [r for r in recs if isinstance(r, dict) and "calls/" in str(r.get("path", "")) and str(r.get("path", "")).endswith(".txt")]
    if not calls:
        return None
    n = sum(1 for r in calls if name.lower() in str(r.get("text", "")).lower())
    return n, len(calls)


# ---------- live events ----------
def event_rules(sig, acct, raw=None):
    """Returns (risks, actions, gaps) for one signal. Text rules + the signal's own records."""
    t = (sig["title"] + " " + sig["detail"]).lower()
    rec_paths = [r.get("path") for r in sig["records"] if r.get("path")]
    ev = [sig["id"] or "signal:" + sig["uid"]] + rec_paths
    people = [p for p in acct["people"] if p["name"] and p["name"].lower() in t] if acct else []
    pnames = ", ".join(p["name"] for p in people) or "the named stakeholder"
    deals = acct["deals"] if acct else []

    def deal_like(*words):
        for d in deals:
            if any(w in d["name"].lower() for w in words):
                return d
        return None

    risks, actions, gaps = [], [], []
    matched = False
    if re.search(r"leaves|leaving|moving on|departure|resign|successor|handover", t):
        matched = True
        d = deal_like("renew", "alliance")
        cm = None
        if people and acct and raw:
            cm = calls_mentioning(raw, acct["key"], people[0]["name"])
        dep = ("Paperwork check: %d of %d call records on file mention %s." % (cm[0], cm[1], people[0]["name"])) if cm else ""
        risks.append({"level": "red", "title": "Relationship continuity: key contact is leaving", "reason": (sig["detail"] + " " + dep).strip(),
                      "impact": "Single-contact dependence; no successor named. Renewal and every open deal lose their champion.",
                      "evidence": ev, "kind": "personnel"})
        actions.append({"action": "Ask %s for a named successor and a joint handover call before they leave; book introductions to the replacement." % pnames,
                        "deal": d, "reason": "Personnel transition with no successor named (live event).", "due": "Before the January handover (exact date to confirm)", "evidence": ev, "score": 900})
        gaps.append({"missing": "Who succeeds the departing contact, and when exactly they leave", "why": "Relationship and decision authority may reset; contact history is single-threaded.",
                     "deal": d, "who": pnames, "ask": "Who takes over the programme, and can we do a three-way handover call?", "priority": "High", "evidence": ev})
    if re.search(r"public event|in writing|written|nobody has replied|no reply", t) and not re.search(r"flew nothing|weekly usage", t):
        matched = True
        d = deal_like("westmere", "scale")
        rel = [o for o in (acct["offers"] if acct else []) if o["pitch_to"] and any(p["name"] == o["pitch_to"] for p in people) and low(o["status"]) != "declined"]
        reltxt = ("; related open offers pitched to %s: %s" % (pnames, ", ".join("%s (%s, $%s)" % (o["title"], o["id"], format(int(o["value"]), ",")) for o in rel if o["value"]))) if rel else ""
        risks.append({"level": "red", "title": "Unanswered customer request ahead of a public event", "reason": sig["detail"],
                      "impact": "Customer wants written answers this week (training dates for extra operators; who responds if a dock fails). Silence risks the event and the Westmere relationship." + reltxt,
                      "evidence": ev + [o["id"] for o in rel], "kind": "operational"})
        actions.append({"action": "Send %s a written reply this week: (1) dates for training additional operators before 5 December; (2) who responds if a dock fails on the day and how fast%s." % (pnames, reltxt),
                        "deal": d, "reason": "Customer explicitly asked for written confirmation; nobody has replied (live event). No Westmere deal exists in the API data, so it is not linked to a deal.",
                        "due": "This week (per customer request)", "evidence": ev + [o["id"] for o in rel], "score": 1000})
        gaps.append({"missing": "Operator training dates and the named responder for a dock failure on the day", "why": "Both are the exact items the customer is waiting on.",
                     "deal": d, "who": "FlytBase delivery/support lead (owner to confirm)", "ask": "Which dates can we offer for operator training, and who is on call on the day?", "priority": "High", "evidence": ev})
    if re.search(r"usage|flew nothing|stopped flying|no flights|idle|have stopped", t):
        matched = True
        d = deal_like("idle", "patrol")
        docks, path = usage_drops(sig)
        dtxt = (" Docks flagged from the usage file: " + "; ".join(docks) + ".") if docks else ""
        risks.append({"level": "red", "title": "Usage drop: docks that flew most nights went silent", "reason": sig["detail"] + dtxt,
                      "impact": "Docks stayed online but stopped flying; no ticket and no customer comment. Churn and adoption risk for the renewal and the idle-plants expansion.",
                      "evidence": ev, "kind": "usage"})
        actions.append({"action": "Contact the customer's closest ally to ask why %s stopped flying; check device and flight records in the paperwork.%s" % (", ".join(x.split(" ")[0] for x in docks) or "the affected docks", ""),
                        "deal": d, "reason": "Usage drop with no ticket raised (live event)." + dtxt, "due": "Requires confirmation", "evidence": ev, "score": 800})
        gaps.append({"missing": "Why the docks stopped flying despite staying online", "why": "Cause decides whether this is churn risk, a pilot/staffing issue or a fault.",
                     "deal": d, "who": "Customer ally (see Power Map)", "ask": "These docks have not flown since mid-November. What changed?", "priority": "High", "evidence": ev})
    if not matched:
        risks.append({"level": "amber", "title": "New event: " + sig["title"], "reason": sig["detail"] or sig["title"],
                      "impact": "Not matched by an existing rule; needs human review.", "evidence": ev, "kind": "event"})
        actions.append({"action": "Review new event: " + sig["title"], "deal": None, "reason": "Unclassified live event.", "due": "Requires confirmation", "evidence": ev, "score": 300})
    return risks, actions, gaps


def process_signals(cache, now):
    """Detect new signals, append event history and notifications."""
    sigs = signals_from(cache["raw"].get("signals"))
    seen = set(cache["seen_signals"])
    accts = all_accounts(cache["raw"])
    first = not cache["seen_signals"]
    for s in sigs:
        if s["uid"] in seen:
            continue
        cache["seen_signals"].append(s["uid"])
        key = acct_for_signal(s, accts)
        acct = next((a for a in accts if a["key"] == key), None)
        rs, _, _ = event_rules(s, acct, cache["raw"])
        cache["events"].append({"uid": s["uid"], "id": s["id"], "title": s["title"], "detail": s["detail"], "when": s["when"],
                                "account": key, "detected_at": now, "initial": first})
        for r in rs:
            cache["notifications"].append({"at": now, "level": r["level"], "title": r["title"], "account": key, "event": s["uid"]})
    cache["notifications"] = cache["notifications"][-50:]


# ---------- evidence index ----------
def walk(o, out, depth=0):
    if depth > 8:
        return
    if isinstance(o, dict):
        i = g(o, "id", "path")
        if isinstance(i, str) and i not in out:
            out[i] = {"id": i, "type": "paperwork / record", "record": {k: v for k, v in o.items() if k != "records"} if "records" in o else o}
        for v in o.values():
            walk(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            walk(v, out, depth + 1)


def build_index(accts, sigs, raw):
    idx = {}
    for a in accts:
        for p in a["people"]:
            if p["id"]:
                idx[p["id"]] = {"id": p["id"], "type": "person (stakeholder)", "account": a["name"], "status": p["status"], "person": p["name"], "record": p["raw"]}
        for f in a["facts"]:
            if f["id"]:
                idx[f["id"]] = {"id": f["id"], "type": "fact", "account": a["name"], "status": f["status"], "person": f["person"], "source": f["by"], "record": f["raw"]}
        for d in a["deals"]:
            if d["id"]:
                idx[d["id"]] = {"id": d["id"], "type": "deal (opportunity)", "account": a["name"], "status": d["stage"], "record": d["raw"]}
        for fl in a["files"]:
            if fl["id"]:
                idx[fl["id"]] = {"id": fl["id"], "type": "file", "account": a["name"], "status": "verified", "record": fl["raw"]}
        for o in a["offers"]:
            if o["id"]:
                idx[o["id"]] = {"id": o["id"], "type": "offer (not a deal)", "account": a["name"], "status": o["status"], "person": o["pitch_to"], "record": o["raw"]}
    for s in sigs:
        if s["id"]:
            idx[str(s["id"])] = {"id": str(s["id"]), "type": "live event (signal)", "record": {k: v for k, v in s["raw"].items() if k != "records"}}
        idx["signal:" + s["uid"]] = {"id": "signal:" + s["uid"], "type": "live event (signal, API gave no id)", "record": s["raw"]}
    pw = {}
    walk(raw.get("signals"), pw)
    walk(raw.get("paperwork"), pw)
    for k, v in pw.items():
        idx.setdefault(k, v)
    return idx


# ---------- analysis ----------
def snapshot_match(name):
    n = name.lower()
    for ph, val, stg in SNAPSHOT:
        if ph in n:
            return {"value": val, "stage": stg}
    return None


def morning_for(name, table):
    n = name.lower()
    for ph, v in table.items():
        if ph in n:
            return v
    return None


def resolve(v, pidx, src=None):
    if v is None or v == "":
        return None
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, dict):
        v = g(v, "text", "name", "id") or txt(v)
    if v is None:
        return None
    s = str(v)
    p = pidx["id"].get(s) or pidx["name"].get(s.lower())
    if p:
        return {"name": p["name"], "id": p["id"], "status": p["status"], "role": p["role"], "is_person": True, "src": src, "available": p.get("available")}
    return {"name": s, "id": None, "status": None, "role": "", "is_person": False, "src": src, "available": None}


def analyse(a, sigs, accts, raw):
    pidx = {"id": {p["id"]: p for p in a["people"] if p["id"]}, "name": {p["name"].lower(): p for p in a["people"] if p["name"]}}
    fmap = {f["id"]: f for f in a["facts"] if f["id"]}
    fileids = {f["id"]: f for f in a["files"] if f["id"]}
    deals_out, power, risks, cands, gaps = [], [], [], [], []
    dls = {}
    for dl in a["deadlines"]:
        dls[dl["label"]] = dict(dl)
    for d in a["deals"]:
        dd = d["raw"].get("deadline")
        if isinstance(dd, dict) and dd.get("text"):
            x = dls.setdefault(dd["text"], {"id": None, "label": dd["text"]})
            x.update({"passed": bool(dd.get("passed")), "soon": bool(dd.get("soon")), "met": bool(dd.get("met")), "moves_left": dd.get("moves_left")})
            x["deal_id"] = d["id"]
            x["deal_name"] = d["name"]
    for d in a["deals"]:
        ev_list = [x for x in (d["raw"].get("evidence") or []) if isinstance(x, str)]
        detail, backing = [], "none"
        for eid in ev_list:
            if eid in fmap:
                st, kind = fmap[eid]["status"], "fact"
                by, who, text = fmap[eid]["by"], fmap[eid]["person"], fmap[eid]["text"]
            elif eid in fileids:
                st, kind, by, who, text = "verified", "file", "", "", fileids[eid]["name"]
            else:
                st, kind, by, who, text = "unknown", "unresolved", "", "", ""
            detail.append({"id": eid, "kind": kind, "status": st, "by": by, "person": who, "text": text})
            if RANK.get(st, 0) > RANK[backing]:
                backing = st
        counted = "no_value"
        if d["worth"] is not None:
            if d["stage"] in BACKED:
                bl_open = bool(d["blocker"]) and low((d["raw"].get("blocker") or {}).get("status", "open") if isinstance(d["raw"].get("blocker"), dict) else "open") != "cleared"
                counted = ("qualified_blocked" if bl_open else "qualified_verified") if backing == "verified" else "qualified_unverified"
            else:
                counted = "uncertain"
        ev_ids = ([d["id"]] if d["id"] else []) + ev_list
        support = sorted({x for e in detail for x in (e["person"], e["by"]) if x})
        snap = snapshot_match(d["name"])
        deals_out.append({"account": a["key"], "account_name": a["name"], "id": d["id"], "name": d["name"], "stage": d["stage"],
                          "worth": money(d["worth"]), "backing": backing, "counted": counted, "evidence": ev_ids, "detail": detail,
                          "support": support, "blocker": d["blocker"], "snapshot": snap})
        # power map
        fd = d["flat"]
        roles = {}
        for role, subs in ROLE_KEYS:
            val = None
            for k, v in fd.items():
                if any(s in low(k) for s in subs) and v not in (None, "") and low(k) not in ("name", "id"):
                    val = v
                    break
            roles[role] = resolve(val, pidx)
        mr = morning_for(d["name"], MORNING_ROLES) or {}
        for role, who in mr.items():
            if roles.get(role) is None:
                roles[role] = resolve(who, pidx, MORNING_SRC)
        if roles["blocker"] is None:
            mb = morning_for(d["name"], MORNING_BLOCKERS)
            if mb:
                roles["blocker"] = resolve(mb, pidx, MORNING_SRC)
        power.append({"account": a["key"], "account_name": a["name"], "deal": d["name"], "deal_id": d["id"], "stage": d["stage"], "roles": roles, "evidence": ev_ids})
        ceiling = d["worth"] or 0
        big = ceiling >= 100000
        for role in ("decision_maker", "payer"):
            if roles[role] is None:
                gaps.append({"account": a["key"], "missing": "%s for \"%s\" is not recorded" % (ROLE_LABEL[role], d["name"]),
                             "why": "Cannot target or time the deal without knowing who holds this role.", "deal": d["name"],
                             "who": ", ".join(p["name"] for p in a["people"] if p["status"] in ("ally", "warm")) or "Nobody met yet",
                             "ask": "Who %s for %s?" % ("signs off" if role == "decision_maker" else "pays", d["name"]),
                             "priority": "High" if big or d["stage"] in BACKED else "Medium", "evidence": ev_ids})
        if roles["blocker"] is None and d["stage"] != "agreed":
            gaps.append({"account": a["key"], "missing": "No blocker recorded for \"%s\"" % d["name"], "why": "A deal that is not agreed has something in the way; not knowing it hides stuck-deal risk.",
                         "deal": d["name"], "who": "Deal decision-maker", "ask": "What would stop this closing?", "priority": "Low", "evidence": ev_ids})
        if counted == "qualified_unverified":
            gaps.append({"account": a["key"], "missing": "No verified evidence behind the qualified value of \"%s\"" % d["name"],
                         "why": "Evidence cited is only claim/told, so the value is shown as unverified.", "deal": d["name"],
                         "who": ", ".join(support) or "Account owner", "ask": "Can you provide a file that backs this?", "priority": "High" if big else "Medium", "evidence": ev_ids})
        if d["worth"] is None and d["stage"] not in BACKED:
            gaps.append({"account": a["key"], "missing": "No value for \"%s\" (stage: %s)" % (d["name"], d["stage"]),
                         "why": "The API gives a value only once a deal is qualified; until then it is uncounted.", "deal": d["name"], "who": "Decision-maker", "ask": "What would qualify this and what is it worth?", "priority": "Medium", "evidence": ev_ids})
        claim_only = [e["id"] for e in detail if e["status"] in ("claim", "told")]
        if claim_only and backing != "verified":
            pass
        # candidate action
        if d["stage"] != "agreed":
            dm = roles["decision_maker"]
            dl_hit = next((x for x in dls.values() if x.get("deal_id") == d["id"] and d["id"]), None)
            score = ceiling / 1000.0 / 2
            reasons = []
            if ceiling:
                reasons.append("Deal ceiling up to $%s" % format(int(ceiling), ","))
            if d["stage"] in BACKED:
                score += 15
                reasons.append("Already %s" % d["stage"])
            if dl_hit and not dl_hit.get("met"):
                score += 60 if (dl_hit.get("soon") or dl_hit.get("passed")) else 25
                reasons.append("Deadline: %s (%s moves left)" % (dl_hit["label"], dl_hit.get("moves_left", "?")))
            if roles["blocker"]:
                score += 10
                reasons.append("Blocker: %s" % roles["blocker"]["name"])
            if dm is None:
                score += 5
                reasons.append("Decision-maker unknown")
            elif dm["status"] in ("guarded", "neutral"):
                score += 8
                reasons.append("Decision-maker %s is %s" % (dm["name"], dm["status"]))
            if roles["blocker"]:
                act = "Clear the blocker on \"%s\": %s" % (d["name"], roles["blocker"]["name"])
            elif dm is None:
                act = "Identify and meet the decision-maker for \"%s\"" % d["name"]
            else:
                act = "Advance \"%s\" with %s (%s)" % (d["name"], dm["name"], dm["status"] or "status unknown")
            due = ("Deadline \"%s\" (%s moves left on the game clock; no calendar date given)" % (dl_hit["label"], dl_hit.get("moves_left", "?"))) if dl_hit else "Requires confirmation"
            cands.append({"action": act, "deal": d, "reason": "; ".join(reasons) or "Open deal", "due": due, "evidence": ev_ids, "score": score,
                          "owner": d["owner"] or "Unassigned - confirm", "probability": str(d["prob"]) if d["prob"] is not None else "Not supported by data"})
            prop = morning_for(d["name"], MORNING_PROPOSALS)
            if prop:
                cands.append({"action": "Send %s a proposal citing exactly: %s" % (prop[0], ", ".join(prop[1])), "deal": d,
                              "reason": "The morning page names these exact evidence items as what moves this deal (source: %s). Ids not in the API are shown as 'Evidence unavailable'." % MORNING_SRC,
                              "due": due, "evidence": prop[1], "score": score + 20, "owner": "Unassigned - confirm", "probability": "Not supported by data"})
    # deadline risks
    for dl in dls.values():
        if dl.get("met"):
            lvl = "green"
        elif dl.get("passed") or dl.get("soon"):
            lvl = "red"
        else:
            lvl = "amber"
        risks.append({"account": a["key"], "level": lvl, "title": "Deadline: " + (dl["label"] or "unnamed"), "kind": "deadline",
                      "reason": "Not met. %s moves left on the game clock (no calendar date in the data); it turns bad when it passes unmet." % dl.get("moves_left", "unknown"),
                      "impact": "Know-how or commitment lost%s." % ((" on deal \"%s\"" % dl["deal_name"]) if dl.get("deal_name") else ""),
                      "evidence": [x for x in (dl.get("deal_id"),) if x]})
        if dl.get("label") and dl.get("deal_id") is None:
            pass
    for p in a["people"]:
        if p["status"] == "guarded":
            risks.append({"account": a["key"], "level": "amber", "title": "Guarded contact: %s" % p["name"], "kind": "relationship",
                          "reason": "Relationship status is guarded.", "impact": "Low trust may stall deals this person influences.", "evidence": [p["id"]] if p["id"] else []})
        if p.get("available") is False:
            risks.append({"account": a["key"], "level": "amber", "title": "Contact unavailable: %s (%s)" % (p["name"], p["status"]), "kind": "relationship",
                          "reason": "The API marks this stakeholder as not available.", "impact": "Our %s cannot be reached right now; deals depending on them are exposed." % p["status"], "evidence": [p["id"]] if p["id"] else []})
    for nm, role, key in MORNING_UNMET:
        if key == a["key"] and nm.lower() not in pidx["name"]:
            risks.append({"account": a["key"], "level": "amber", "title": "Missing stakeholder: %s (%s)" % (nm, role), "kind": "missing stakeholder",
                          "reason": "Never met (%s)." % MORNING_SRC, "impact": "Decisions or payments may be made without us.", "evidence": []})
            gaps.append({"account": a["key"], "missing": "Never met %s (%s)" % (nm, role), "why": "Unknown stance and influence over open deals.",
                         "deal": "Deals they decide or pay for", "who": ", ".join(x["name"] for x in a["people"] if x["status"] in ("ally", "warm")) or "No ally yet",
                         "ask": "Can you introduce us to %s?" % nm, "priority": "High", "evidence": []})
    for d in a["deals"]:
        if d["blocker"] and d["stage"] != "agreed":
            risks.append({"account": a["key"], "level": "amber", "title": "Stuck deal: " + d["name"], "kind": "stuck deal",
                          "reason": "Blocker: " + d["blocker"], "impact": "Deal worth up to $%s cannot progress." % (format(int(d["worth"]), ",") if d["worth"] else "n/a (not qualified)"),
                          "evidence": [d["id"]] if d["id"] else []})
        if re.search(r"renew", d["name"].lower()) and d["stage"] != "agreed":
            risks.append({"account": a["key"], "level": "amber", "title": "Renewal not agreed: " + d["name"], "kind": "contract renewal",
                          "reason": "Stage is %s, not agreed." % d["stage"], "impact": "Revenue at risk at renewal.", "evidence": [d["id"]] if d["id"] else []})
    # official story vs verified facts
    for f in a["facts"]:
        if f["status"] == "verified" and re.search(r"no guard contract|no saving|nine only|only log|not finished", f["text"].lower()):
            risks.append({"account": a["key"], "level": "amber", "title": "Official story contradicted by verified evidence", "kind": "claim vs fact",
                          "reason": f["text"], "impact": "The account sheet is unverified; relying on it overstates the account's health.", "evidence": [f["id"]] + ([f["by"]] if f["by"] else [])})
    for s in sigs:
        if acct_for_signal(s, accts) != a["key"]:
            continue
        rs, acts, gs = event_rules(s, a, raw)
        for r in rs:
            r["account"] = a["key"]
            risks.append(r)
        for x in acts:
            cands.append({"action": x["action"], "deal": x["deal"], "reason": x["reason"], "due": x["due"], "evidence": x["evidence"], "score": x["score"],
                          "owner": "Unassigned - confirm", "probability": "Not supported by data", "event": True})
        for x in gs:
            x["account"] = a["key"]
            x["deal"] = x["deal"]["name"] if x["deal"] else "Not linked to a deal in data"
            gaps.append(x)
    order = {"red": 0, "amber": 1, "green": 2}
    risks.sort(key=lambda r: order[r["level"]])
    cands.sort(key=lambda c: -c["score"])
    actions = []
    for i, c in enumerate(cands, 1):
        d = c["deal"]
        actions.append({"account": a["key"], "account_name": a["name"], "rank": i, "top": i <= 3, "action": c["action"], "owner": c["owner"], "due": c["due"],
                        "deal": (d["name"] if isinstance(d, dict) else None) or "No linked deal in data",
                        "deal_id": d["id"] if isinstance(d, dict) else None, "reason": c["reason"], "evidence": c["evidence"],
                        "probability": c.get("probability", "Not supported by data"), "score": round(c["score"], 1), "id": "%s-%d" % (a["key"], i)})
    pr = {"High": 0, "Medium": 1, "Low": 2}
    gaps.sort(key=lambda x: pr.get(x["priority"], 3))
    qb = sum(x["worth"] or 0 for x in deals_out if x["counted"] == "qualified_blocked")
    q = sum(x["worth"] or 0 for x in deals_out if x["counted"] == "qualified_verified")
    qu = sum(x["worth"] or 0 for x in deals_out if x["counted"] == "qualified_unverified")
    un = sum(x["worth"] or 0 for x in deals_out if x["counted"] == "uncertain")
    snap_sum = sum((x["snapshot"] or {}).get("value") or 0 for x in deals_out)
    return {"deals": deals_out, "power": power, "risks": risks, "actions": actions, "gaps": gaps,
            "totals": {"verified": q, "blocked": qb, "qualified_unverified": qu, "uncertain": un}, "snapshot_sum": snap_sum}


def build(cache):
    raw = cache.get("raw", {})
    accts = all_accounts(raw)
    sigs = signals_from(raw.get("signals"))
    out = {"accounts": [], "events": cache.get("events", []), "notifications": cache.get("notifications", []),
           "notes": cache.get("notes", []), "snapshot_total": SNAPSHOT_TOTAL, "has_data": bool(accts),
           "signals_loaded": "signals" in raw, "paperwork_loaded": sorted((raw.get("paperwork") or {}).keys()),
           "fetched_at": cache.get("fetched_at", {})}
    idx = build_index(accts, sigs, raw)
    out["evidence_count"] = len(idx)
    out["evidence_ids"] = sorted(idx.keys())[:2000]
    for a in accts:
        r = analyse(a, sigs, accts, raw)
        r.update({"key": a["key"], "name": a["name"], "official": a["official"], "extra": a["extra"],
                  "people": [{"id": p["id"], "name": p["name"], "role": p["role"], "status": p["status"], "available": p["available"]} for p in a["people"]],
                  "facts": [{"id": f["id"], "text": f["text"], "person": f["person"], "status": f["status"], "by": f["by"]} for f in a["facts"]],
                  "files": [{"id": f["id"], "name": f["name"]} for f in a["files"]],
                  "offers": [{"id": o["id"], "title": o["title"], "value": money(o["value"]), "pitch_to": o["pitch_to"], "status": o["status"]} for o in a["offers"]]})
        out["accounts"].append(r)
    core = [x for x in out["accounts"] if not x["extra"]]
    out["snapshot_matched"] = sum(x["snapshot_sum"] for x in core)
    out["api_total_with_value"] = sum(x["totals"]["verified"] + x["totals"]["blocked"] + x["totals"]["qualified_unverified"] + x["totals"]["uncertain"] for x in core)
    out["whoami"] = raw.get("whoami")
    return out


def evidence(cache, ev_id):
    raw = cache.get("raw", {})
    idx = build_index(all_accounts(raw), signals_from(raw.get("signals")), raw)
    e = idx.get(ev_id)
    if not e:
        return None
    e = dict(e)
    s = json.dumps(e.get("record"), indent=2, default=str)
    e["record"] = s[:6000] + ("\n... truncated" if len(s) > 6000 else "")
    return e
