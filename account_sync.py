#!/usr/bin/env python3
"""Nightly Xcelerator -> Comet account detail sync.
Pulls every active Comet client page from Xcelerator and uploads the form fields
to account_sync_raw. All diffing / applying happens in Supabase
(account_sync_apply), so this script never edits client_accounts directly."""
import asyncio, os, re, json, uuid, traceback, requests
from datetime import datetime, timezone
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']; PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL']; KEY = os.environ['SUPABASE_KEY']
H = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'}
RUN = str(uuid.uuid4())

def now(): return datetime.now(timezone.utc).isoformat()
def log(m): print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)

def sb(method, path, body=None, prefer='return=minimal'):
    r = requests.request(method, f'{SUPA}/rest/v1/{path}', headers={**H, 'Prefer': prefer}, json=body, timeout=60)
    if r.status_code >= 300: log(f'supabase {path} {r.status_code}: {r.text[:200]}')
    return r

def heartbeat(ok, n, err=None):
    row = {'scraper_name': 'account_sync', 'last_error': err, 'order_count': n}
    if ok: row['last_success'] = now()
    sb('POST', 'scraper_heartbeats?on_conflict=scraper_name', row, 'resolution=merge-duplicates,return=minimal')

def login_urls():
    urls = []
    try:  # use exactly the URL the working order scraper uses
        src = Path('/opt/xcelerator/scripts/order_scraper.py').read_text()
        m = re.search(r"async def login\(pg\):\s*await pg\.goto\('([^']+)'", src)
        if m: urls.append(m.group(1))
    except Exception: pass
    g = (os.environ.get('GOCTL_URL') or '').strip().strip('"\'')
    if g: urls += [g, g.rstrip('/') + '/Main/home']
    urls += ['https://www.goctl.com/Main/home', 'https://www.goctl.com/']
    return list(dict.fromkeys(u for u in urls if u.startswith('http')))

async def login(pg):
    seen = []
    for attempt in range(2):
        for u in login_urls():
            try:
                await pg.goto(u, wait_until='domcontentloaded')
                await pg.wait_for_selector('input[name="UserName"]', timeout=20000)
            except Exception:
                seen.append(f'{u} -> {pg.url} [{(await pg.title())[:40]}]'); continue
            await pg.type('input[name="UserName"]', USER, delay=40)
            await pg.type('input[name="Password"]', PASS, delay=40)
            await pg.click('button[type="submit"]')
            try:
                await pg.wait_for_load_state('load', timeout=30000)
            except Exception:
                await pg.wait_for_timeout(5000)
            await asyncio.sleep(6)
            return
        await asyncio.sleep(20)
    raise RuntimeError('login form not found: ' + ' | '.join(seen)[:400])

async def client_list(pg):
    await pg.evaluate("() => { openFrame('ClientMaster'); }")
    await asyncio.sleep(6)
    panel = next((f for f in pg.frames if 'Panel.aspx' in f.url and 'Client' in f.url and 'Top' not in f.url), None)
    if not panel: raise RuntimeError('ClientMaster panel not found')
    await panel.evaluate("""() => {
        document.getElementById('TerminalID').value = '22';
        document.getElementById('Status').value = 'A';
        document.getElementById('MaxRecords').value = '9999';
        document.loadtoolbarform.submit(); }""")
    js = """() => { const out = [];
        document.querySelectorAll('a, [onclick]').forEach(a => {
          const s = (a.getAttribute('onclick') || '') + ' ' + (a.getAttribute('href') || '');
          const m = s.match(/WM_toggle\\(\\s*['"]X(\\d+)['"]/) || s.match(/oCM\\(\\s*['"]?(\\d+)/) || s.match(/ClientID=(\\d+)/);
          if (m) out.push([m[1], a.innerText.trim()]); });
        return out; }"""
    best, diag = [], []
    for _ in range(12):
        await asyncio.sleep(5)
        diag = []
        for f in pg.frames:
            try: found = await f.evaluate(js)
            except Exception: found = []
            diag.append(f"{f.url.split('goctl.com')[-1][:60]}={len(found)}")
            if len(found) > len(best): best = found
        if len(best) >= 100: break
    seen, out = set(), []
    for cid, name in best:
        if cid not in seen and name: seen.add(cid); out.append((int(cid), name))
    if len(out) < 100: raise RuntimeError(f'only {len(out)} clients found; frames: ' + ', '.join(diag)[:400])
    return out

# Opens each account's Client Profile (ClientMaster.aspx, the page Xcelerator itself loads)
# and keeps ONLY the contact/address fields below - nothing else leaves Xcelerator.
FETCH_JS = """async (ids) => {
  const KEEP = /^(CompanyName|AccountNo|Status|ClientStatus|Terms|PaymentTerms|PrContactName|PrContactTitle|Phone|Email|MailAddr(ContactName|Street|Street2|City|State|Zip|Phone|Email)|EmailInvAddresses|PODemailAddress)$/;
  return Promise.all(ids.map(async id => { try {
    const r = await fetch('/Client/ClientMaster/ClientMaster.aspx?ClientID=' + id + '&TerminalID=0&JumpToTab=&TimezoneAbbrev=CDT', {credentials:'include'});
    const d = new DOMParser().parseFromString(await r.text(), 'text/html'); const f = {};
    d.querySelectorAll('input,select,textarea').forEach(e => { const n = e.getAttribute('name') || e.id; if (!n || !KEEP.test(n)) return;
      const v = e.tagName === 'SELECT' ? ((e.querySelector('option[selected]') || {}).textContent || '')
              : e.tagName === 'TEXTAREA' ? e.textContent : (e.getAttribute('value') || '');
      f[n] = v.trim().slice(0, 500); });
    return [id, r.status, d.title, f]; } catch (e) { return [id, 0, String(e), {}]; } })); }"""

async def run():
    from playwright.async_api import async_playwright
    sb('POST', 'account_sync_runs', {'run_id': RUN, 'status': 'running'})
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width': 1440, 'height': 900})
        pg.set_default_timeout(60000)
        log('login'); await login(pg)
        clients = await client_list(pg)
        log(f'{len(clients)} active clients in Xcelerator')
        names = dict(clients); rows, errs = [], 0
        ids = [c for c, _ in clients]
        for i in range(0, len(ids), 6):
            for cid, status, title, fields in await pg.evaluate(FETCH_JS, ids[i:i+6]):
                acct = (fields.get('AccountNo') or '').strip()
                if status != 200 or not acct.isdigit():
                    errs += 1; continue
                rows.append({'run_id': RUN, 'xc_client_id': cid, 'account_number': int(acct),
                             'company_name': fields.get('CompanyName') or names.get(cid),
                             'page_email': fields.get('Email') or None, 'fields': fields})
            if len(rows) >= 50:
                sb('POST', 'account_sync_raw', rows); rows = []
            await asyncio.sleep(0.3)
        if rows: sb('POST', 'account_sync_raw', rows)
        await br.close()
    sb('PATCH', f'account_sync_runs?run_id=eq.{RUN}', {'fetch_errors': errs})
    if errs > len(clients) * 0.2: raise RuntimeError(f'{errs} of {len(clients)} account pages failed - not applying')
    r = requests.post(f'{SUPA}/rest/v1/rpc/account_sync_apply', headers=H, json={'p_run': RUN}, timeout=300)
    log(f'apply: {r.status_code} {r.text[:300]}')
    if r.status_code >= 300: raise RuntimeError(f'apply failed {r.status_code}')
    heartbeat(True, len(clients))
    log(f'done: {len(clients)} clients, {errs} fetch errors')

if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as e:
        log('FAILED: ' + traceback.format_exc()[-800:])
        try:
            heartbeat(False, 0, str(e)[:300])
            sb('PATCH', f'account_sync_runs?run_id=eq.{RUN}', {'status': 'error', 'note': str(e)[:500], 'finished_at': now()})
        except Exception: pass
        raise SystemExit(1)
