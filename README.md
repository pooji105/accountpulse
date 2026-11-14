# AccountPulse - AI-Powered Customer Success Command Center

Live CRM for the Questathon challenge. It reads two customer accounts through the Questathon MCP server and answers five questions per account: what the book is worth, who holds the power, what to do first, what is about to go wrong, and what we still do not know. Every number links to an evidence ID.

## Run locally
1. `pip install -r requirements.txt`
2. Set the token on the server side only (never commit it):
   - Mac/Linux: `export AQ_TOKEN=your_token`
   - Windows PowerShell: `$env:AQ_TOKEN="your_token"`
3. `python app.py` then open http://localhost:5000

The first sync takes about 4 minutes (1 API call per minute): accounts, signals, paperwork for each account. After that it polls `get_signals` / `whoami` automatically. The page refreshes itself.

## Deploy on Render
1. Push this folder to a public GitHub repo (`data/cache.json`, `.env` are git-ignored).
2. Render > New > Web Service > connect the repo.
3. Build command: `pip install -r requirements.txt`. Start command: `gunicorn app:app --workers 1 --threads 4`.
4. Environment > add `AQ_TOKEN` with your token. Deploy.

Keep the instance count at 1 so only one process calls the API. On free plans the cache resets on redeploy and the sync repeats (about 4 minutes).

## Files
- `mcp_client.py` - JSON-RPC client, 62-second call scheduler, cache, write_note queue
- `crm_engine.py` - evidence index, deal classification, power map, actions, risks, gaps, live-event rules
- `app.py` - Flask routes (`/api/state`, `/api/evidence/<id>`, `/api/notes`, `/api/datacheck`)
- `templates/`, `static/` - dashboard (HTML/CSS/JS, Chart.js)
- `docs/` - thinking doc and video script

## Security
The token is read from `AQ_TOKEN` on the server, is never sent to the browser, and is never written to logs or the cache.

## Known limits
See `docs/THINKING_DOC.md`. Field names in the API response are matched tolerantly; the Data Check page (Data Sources) shows the raw response shape so you can verify it against your real data.
