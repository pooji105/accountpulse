import json
import os
import time

from flask import Flask, jsonify, render_template, request

import crm_engine
import mcp_client

app = Flask(__name__)
sched = mcp_client.Scheduler()
if not os.environ.get("NO_SCHEDULER"):
    sched.start()


def sync_status(c):
    m = c["meta"]
    gap = max(0, int(mcp_client.MIN_GAP - (time.time() - m["last_call"]))) if m["last_call"] else 0
    return {"token_set": bool(os.environ.get("AQ_TOKEN")), "calls": m["calls"], "last_success": m["last_success"],
            "next_call_in": gap if os.environ.get("AQ_TOKEN") else None, "next_job": sched.describe_next(c) if os.environ.get("AQ_TOKEN") else None,
            "busy": sched.current, "errors": c["errors"][-5:], "log": c["log"][-15:], "fetched_at": c["fetched_at"]}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def state():
    c = mcp_client.snapshot()
    s = crm_engine.build(c)
    s["sync"] = sync_status(c)
    return jsonify(s)


@app.route("/api/evidence/<path:ev_id>")
def evidence(ev_id):
    e = crm_engine.evidence(mcp_client.snapshot(), ev_id)
    if not e:
        return jsonify({"error": "Evidence unavailable", "id": ev_id}), 404
    return jsonify(e)


@app.route("/api/notes", methods=["POST"])
def notes():
    d = request.get_json(silent=True) or {}
    text = (d.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text is required"}), 400
    n = mcp_client.add_note(text[:4000], d.get("account"), d.get("kind", "note"), (d.get("title") or "")[:200])
    return jsonify(n)


@app.route("/api/datacheck")
def datacheck():
    c = mcp_client.snapshot()
    raw = c["raw"]

    def shape(o, depth=0):
        if depth > 3:
            return "..."
        if isinstance(o, dict):
            return {k: shape(v, depth + 1) for k, v in list(o.items())[:25]}
        if isinstance(o, list):
            return [shape(o[0], depth + 1), "(%d items)" % len(o)] if o else []
        return type(o).__name__
    return jsonify({"shapes": {k: shape(v) for k, v in raw.items()}, "raw": {k: v for k, v in raw.items() if k != "paperwork"},
                    "paperwork_keys": list((raw.get("paperwork") or {}).keys()), "sync": sync_status(c)})


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "token_set": bool(os.environ.get("AQ_TOKEN"))})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
