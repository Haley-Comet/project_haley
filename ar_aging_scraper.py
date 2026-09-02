#!/opt/xcelerator/venv/bin/python3
"""ar_aging_scraper.py - full AR aging snapshot from goctl Standard Reports > Aged Trial Balance.
Terminal Comet, balance > 0, all client statuses. One row per account -> public.ar_aging_snapshot
(upsert on run_date+account_number). Feeds Boardroom Ops Pulse via command_center_data().
Fail-closed: if the parsed rows do not reconcile with the report's own Count/total row, nothing is written.
"""
import asyncio, os, re, sys, json, html, requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip())
USER = os.environ['GOCTL_USER']; PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL'].rstrip('/'); KEY = os.environ['SUPABASE_KEY']
HDRS = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal'}
TERMINAL = '22'  # Comet
CT = ZoneInfo('America/Chicago')
def log(msg): print(f"[{datetime.now(CT).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)
def money(s):
    s = (s or '').strip().replace('$', '').replace(',', '')
    neg = s.startswith('(') and s.endswith(')') or s.startswith('-')
    s = s.strip('()-') or '0'
    v = float(s); return -v if neg else v
def cells(r): return [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', c))).strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
def parse(page_html):
    tbls = [t for t in re.findall(r'<table[^>]*class="table"[^>]*>(.*?)</table>', page_html, re.S)]
    for t in tbls:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S)
        if not rows: continue
        head = cells(rows[0])
        if head[:3] != ['AccountNo', 'Company Name', 'Total']: continue
        exp = ['AccountNo', 'Company Name', 'Total', 'Unapplied', 'Current', '31-60', '61-90', '91-120', 'Over 120']
        if head != exp: raise RuntimeError(f'unexpected ATB columns: {head}')
        out, ctrl = [], None
        for r in rows[1:]:
            c = cells(r)
            if len(c) < 9: continue
            if c[1].startswith('Count:'):
                n = int(re.search(r'\((\d+)\)', c[1]).group(1))
                ctrl = {'n': n, 'total': money(c[2]), 'unapplied': money(c[3]), 'current': money(c[4]),
                        'b31': money(c[5]), 'b61': money(c[6]), 'b91': money(c[7]), 'b120': money(c[8])}
                continue
            if not c[0].isdigit(): continue
            out.append({'account_number': int(c[0]), 'company_name': c[1][:200], 'total_owed': money(c[2]),
                        'amt_unapplied': money(c[3]), 'amt_current': money(c[4]), 'amt_31_60': money(c[5]),
                        'amt_61_90': money(c[6]), 'amt_91_120': money(c[7]), 'amt_over_120': money(c[8])})
        return out, ctrl
    raise RuntimeError('ATB results table not found')
async def fetch():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width': 1440, 'height': 900}); pg.set_default_timeout(45000)
        try:
            await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
            await pg.type('input[name="UserName"]', USER, delay=30); await pg.type('input[name="Password"]', PASS, delay=30)
            await pg.click('button[type="submit"]'); await pg.wait_for_load_state('load'); await asyncio.sleep(6)
            await pg.evaluate("() => { openFrame('StandardRep'); }")
            sub = None
            for _ in range(20):
                await asyncio.sleep(1)
                sub = next((f for f in pg.frames if 'standardreportssubframe' in (f.url or '')), None)
                if sub and await sub.evaluate("() => document.body && document.body.innerText.includes('Aged Trial Balance')"): break
            if not sub: raise RuntimeError('Standard Reports subframe not found')
            await sub.evaluate("""() => { const el=[...document.querySelectorAll('a,li,span,div,td')].find(e=>e.children.length===0 && e.innerText.trim()==='Aged Trial Balance'); if(!el) throw new Error('ATB link not found'); el.click(); }""")
            atb = None
            for _ in range(30):
                await asyncio.sleep(1)
                atb = next((f for f in pg.frames if 'AgedTrialBalance' in (f.url or '')), None)
                if atb and await atb.evaluate("() => !!(document.Form1 && document.Form1.Terminals)"): break
            if not atb: raise RuntimeError('AgedTrialBalance frame not ready')
            closing = await atb.evaluate("""(t) => { const f=document.Form1; for (const o of f.Terminals.options) o.selected=(o.value===t);
                for (const o of f.ClientStatus.options) o.selected=(o.value==='All'); f.ResultsFocus.value='GreaterThan'; f.OrderBy.value='CM.CompanyName';
                f.daysOutstanding.value='0'; f.AccountNo.value=''; const d=f.ClosingDate.value; f.submit(); return d; }""", TERMINAL)
            page_html = None
            for _ in range(24):
                await asyncio.sleep(5)
                atb = next((f for f in pg.frames if 'AgedTrialBalance' in (f.url or '')), None)
                try:
                    if atb and await atb.evaluate("() => document.body.innerText.includes('Count:')"):
                        page_html = await atb.content(); break
                except Exception: pass
            if not page_html: raise RuntimeError('ATB results did not render')
            return closing, page_html
        finally:
            await br.close()
def main():
    closing, page_html = asyncio.run(fetch())
    rows, ctrl = parse(page_html)
    run_date = datetime.strptime(closing, '%m/%d/%Y').date().isoformat()
    tot = round(sum(r['total_owed'] for r in rows), 2)
    if not ctrl or len(rows) != ctrl['n'] or abs(tot - ctrl['total']) > 0.05:
        log(f"RECONCILE FAIL rows={len(rows)} ctrl={ctrl} sum={tot} -> nothing written"); sys.exit(2)
    if len(rows) < 10:
        log(f"SANITY FAIL only {len(rows)} rows -> nothing written"); sys.exit(2)
    run_id = datetime.now(CT).strftime('atb-%Y%m%d-%H%M%S')
    for r in rows: r.update({'run_date': run_date, 'run_id': run_id, 'source': 'goctl_aged_trial_balance'})
    for i in range(0, len(rows), 200):
        resp = requests.post(f'{SUPA}/rest/v1/ar_aging_snapshot?on_conflict=run_date,account_number', headers=HDRS, json=rows[i:i+200], timeout=60)
        if resp.status_code not in (200, 201, 204):
            log(f"UPSERT FAIL {resp.status_code} {resp.text[:300]}"); sys.exit(3)
    past_due = round(ctrl['b31'] + ctrl['b61'] + ctrl['b91'] + ctrl['b120'], 2)
    log(f"OK run_date={run_date} accounts={len(rows)} total={ctrl['total']:.2f} current={ctrl['current']:.2f} past_due={past_due:.2f} unapplied={ctrl['unapplied']:.2f} run_id={run_id}")
if __name__ == '__main__':
    try: main()
    except SystemExit: raise
    except Exception as e:
        log(f"ERROR {type(e).__name__}: {str(e)[:400]}"); sys.exit(1)
