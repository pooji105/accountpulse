"""Questathon MCP client + rate-limited background scheduler.

One API call per minute per token (writes included): every call goes through
the scheduler, which waits at least MIN_GAP seconds between calls. Browsers never
trigger API calls; they only read the cache.
"""
import copy
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests

import crm_engine

MCP_URL = os.environ.get("MCP_URL", "https://questathon.aihackerscollective.com/api/public/mcp")
MIN_GAP = 62
CACHE_PATH = os.environ.get("CACHE_PATH", "/tmp/accountpulse-cache.json")
_lock = threading.RLock()
_cache = None


class McpError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _defaults(c):
    c.setdefault("meta", {})
    for k, v in (("last_call", 0), ("last_success", None), ("calls", 0), ("cycle", 0), ("fails", {})):
        c["meta"].setdefault(k, v)
    c.setdefault("raw", {})
    c.setdefault("errors", [])
    c.setdefault("log", [])
    c.setdefault("seen_signals", [])
    c.setdefault("events", [])
    c.setdefault("notifications", [])
    c.setdefault("notes", [])
    c.setdefault("fetched_at", {})
    return c


def _load():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
        _defaults(_cache)
    return _cache


def _save():
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, default=str)
    os.replace(tmp, CACHE_PATH)


def snapshot():
    with _lock:
        return copy.deepcopy(_load())


def add_note(text, account, kind, title):
    with _lock:
        c = _load()
        n = {"local_id": "n%d" % (int(time.time() * 1000)), "text": text, "account": account or None,
             "kind": kind if kind in ("note", "task", "risk", "next_step") else "note",
             "title": title or None, "status": "pending", "created": now_iso(), "tries": 0, "error": None}
        c["notes"].append(n)
        _save()
        return n


def call_tool(name, args=None):
    token = os.environ.get("AQ_TOKEN")
    if not token:
        raise McpError("AQ_TOKEN is not set on the server")
    payload = {"jsonrpc": "2.0", "id": int(time.time() * 1000), "method": "tools/call",
               "params": {"name": name, "arguments": args or {}}}
    try:
        r = requests.post(MCP_URL, data=json.dumps(payload), timeout=45, headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": "Bearer " + token})
    except requests.RequestException as e:
        raise McpError("Network error: %s" % type(e).__name__)
    if r.status_code in (401, 403):
        raise McpError("Authentication failed (HTTP %d): check AQ_TOKEN" % r.status_code)
    if r.status_code == 429:
        raise McpError("Rate limited (HTTP 429)")
    if r.status_code >= 400:
        raise McpError("HTTP %d: %s" % (r.status_code, r.text[:200]))
    body = r.text
    if "event-stream" in r.headers.get("content-type", ""):
        datas = [ln[5:].strip() for ln in body.splitlines() if ln.startswith("data:")]
        body = datas[-1] if datas else "{}"
    try:
        msg = json.loads(body)
    except ValueError:
        raise McpError("Response was not JSON")
    if msg.get("error"):
        raise McpError(str(msg["error"].get("message", msg["error"]))[:300])
    result = msg.get("result", {})
    content = result.get("content") or []
    text = content[0].get("text", "") if content else ""
    if result.get("isError"):
        raise McpError(text[:300] or "Tool returned an error")
    try:
        return json.loads(text)
    except ValueError:
        return text if text else result


class Scheduler:
    def __init__(self):
        self.thread = None
        self.current = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _pick(self, c):
        raw = c["raw"]
        fails = c["meta"]["fails"]

        def ok(tag):
            return fails.get(tag, 0) < 3

        if "accounts" not in raw and ok("accounts"):
            return ("get_my_accounts", {}, "accounts")
        keys = crm_engine.account_keys(raw.get("accounts"))
        if "signals" not in raw and ok("signals"):
            return ("get_signals", {}, "signals")
        for n in c["notes"]:
            if n["status"] == "pending":
                args = {"text": n["text"], "kind": n["kind"]}
                if n.get("account"):
                    args["account"] = n["account"]
                if n.get("title"):
                    args["title"] = n["title"]
                return ("write_note", args, "note:" + n["local_id"])
        for k in keys:
            if k not in raw.get("paperwork", {}) and ok("paperwork:" + k):
                return ("get_all_paperwork", {"account": k}, "paperwork:" + k)
        for nid in crm_engine.new_account_ids(raw.get("whoami")):
            if nid not in raw.get("new_accounts", {}) and ok("new:" + nid):
                return ("get_new_account", {"account": nid}, "new:" + nid)
        seq = ["signals", "signals", "whoami"]
        tag = seq[c["meta"]["cycle"] % len(seq)]
        c["meta"]["cycle"] += 1
        return ("get_signals" if tag == "signals" else "whoami", {}, tag)

    def describe_next(self, c):
        try:
            j = self._pick(copy.deepcopy(c))
            return j[0] + (" " + json.dumps(j[1]) if j[1] and j[0] != "write_note" else "")
        except Exception:
            return None

    def _loop(self):
        while True:
            try:
                if os.environ.get("AQ_TOKEN"):
                    with _lock:
                        c = _load()
                        wait = MIN_GAP - (time.time() - c["meta"]["last_call"])
                        job = self._pick(c) if wait <= 0 else None
                    if job:
                        self._run(job)
                time.sleep(3)
            except Exception as e:  # never let the thread die
                with _lock:
                    _load()["errors"].append({"at": now_iso(), "tool": "scheduler", "error": str(e)[:200]})
                time.sleep(10)

    def _run(self, job):
        name, args, tag = job
        with _lock:
            c = _load()
            c["meta"]["last_call"] = time.time()
            c["meta"]["calls"] += 1
            self.current = name
            _save()
        try:
            res = call_tool(name, args)
            err = None
        except Exception as e:
            res, err = None, str(e)[:300]
        with _lock:
            c = _load()
            c["meta"]["last_call"] = time.time()
            self.current = None
            entry = {"at": now_iso(), "tool": name, "args": {k: v for k, v in args.items() if k != "text"}, "ok": err is None}
            if err:
                entry["error"] = err
                c["errors"] = (c["errors"] + [{"at": entry["at"], "tool": name, "error": err}])[-20:]
                c["meta"]["fails"][tag] = c["meta"]["fails"].get(tag, 0) + 1
                if tag.startswith("note:"):
                    for n in c["notes"]:
                        if "note:" + n["local_id"] == tag:
                            n["tries"] += 1
                            n["error"] = err
                            if n["tries"] >= 2:
                                n["status"] = "failed"
            else:
                c["meta"]["last_success"] = entry["at"]
                c["meta"]["fails"].pop(tag, None)
                c["fetched_at"][tag] = entry["at"]
                if tag == "accounts":
                    c["raw"]["accounts"] = res
                elif tag.startswith("paperwork:"):
                    c["raw"].setdefault("paperwork", {})[tag.split(":", 1)[1]] = res
                elif tag == "signals":
                    c["raw"]["signals"] = res
                    crm_engine.process_signals(c, now_iso())
                elif tag == "whoami":
                    c["raw"]["whoami"] = res
                elif tag.startswith("new:"):
                    c["raw"].setdefault("new_accounts", {})[tag.split(":", 1)[1]] = res
                elif tag.startswith("note:"):
                    for n in c["notes"]:
                        if "note:" + n["local_id"] == tag:
                            n["status"] = "saved"
                            n["error"] = None
                            n["saved_at"] = entry["at"]
                            n["response"] = res if isinstance(res, (dict, str)) else None
            c["log"] = (c["log"] + [entry])[-60:]
            _save()
