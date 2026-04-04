import asyncio, os, json, requests, re
from datetime import datetime
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL']
KEY  = os.environ['SUPABASE_KEY']
OUT  = Path('/opt/xcelerator/output')
HDRS = {
    'apikey': KEY, 'Authorization': f'Bearer {KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'resolution=merge-duplicates,return=minimal'
}

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(5)

def parse_money(s):
    if not s: return 0.0
    try: return float(re.sub(r'[^0-9.\-]', '', str(s)))
    except: return 0.0

def days_to_bucket(days_late):
    if days_late >= 120: return 120
    if days_late >= 90:  return 90
    if days_late >= 60:  return 60
    if days_late >= 30:  return 30
    return 0

def days_to_bucket_label(days_late):
    if days_late >= 120: return '120+ Days'
    if days_late >= 90:  return '90-119 Days'
    if days_late >= 60:  return '60-89 Days'
    if days_late >= 30:  return '30-59 Days'
    return 'Current'

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now()
    today = now.strftime('%m/%d/%Y')
    print(f"[{now.strftime('%H:%M:%S')}] AR Scraper starting...")

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("    Logging in...")
        await login(pg)

        # Open Collections frame
        print("    Opening Collections...")
        await pg.evaluate("() => { openFrame('Collections'); }")
        await asyncio.sleep(6)

        coll_frame = next((f for f in pg.frames if 'Collections.aspx' in f.url), None)
        if not coll_frame:
            print("    ERROR: Collections frame not found"); await br.close(); return

        # Select Comet only and run
        print("    Running collections for Comet...")
        await coll_frame.evaluate("""() => {
            const sel = document.querySelector('select[name="Terminals"]');
            if (sel) {
                for (let opt of sel.options) opt.selected = opt.text.trim() === 'Comet';
            }
        }""")
        await coll_frame.click('text=Run Collections')
        await asyncio.sleep(6)

        # Find the results frame
        results_frame = next(
            (f for f in pg.frames if 'CollectionsControls.aspx' in f.url and 'METHOD' not in f.url),
            next((f for f in pg.frames if 'CollectionsControls' in f.url), None)
        )

        # Parse the table from whichever frame has the data
        records = []
        for frame in pg.frames:
            if 'CollectionsControls' in frame.url or 'Collections' in frame.url:
                try:
                    rows = await frame.evaluate("""() => {
                        const rows = Array.from(document.querySelectorAll('tr'));
                        return rows.map(row => {
                            const cells = Array.from(row.querySelectorAll('td'));
                            return cells.map(c => c.innerText.trim().replace(/\\s+/g,' '));
                        }).filter(r => r.length >= 7 && r[1] && /^\\d+$/.test(r[1].trim()));
                    }""")
                    if rows:
                        print(f"    Found {len(rows)} rows in {frame.url.split('goctl.com')[1][:60]}")
                        records = rows
                        break
                except: pass

        if not records:
            print("    No records found — saving HTML for inspection")
            for frame in pg.frames:
                if 'Collections' in frame.url:
                    try:
                        html = await frame.content()
                        if len(html) > 1000:
                            (OUT/f'ar_debug_{frame.url.split("/")[-1].split("?")[0]}.html').write_text(html)
                    except: pass
            await br.close()
            return

        # Map rows to ar_collections schema
        # Columns: Company | AccountNo | Last Invoice | Last Payment | YTD Invoice | YTD Paid | Days Old | Days Late | Past Due Amt
        ar_rows = []
        for row in records:
            try:
                company    = row[0]
                account_no = row[1].strip()
                last_inv   = row[2] if len(row) > 2 else ''
                last_pmt   = row[3] if len(row) > 3 else ''
                ytd_inv    = parse_money(row[4]) if len(row) > 4 else 0
                ytd_paid   = parse_money(row[5]) if len(row) > 5 else 0
                days_old   = int(row[6]) if len(row) > 6 and row[6].strip().isdigit() else 0
                days_late  = int(row[7]) if len(row) > 7 and row[7].strip().isdigit() else 0
                past_due   = parse_money(row[8]) if len(row) > 8 else 0

                if past_due <= 0:
                    continue  # Skip accounts with no past due balance

                ar_rows.append({
                    'run_id': f"scraper-{now.strftime('%Y%m%d')}",
                    'account_number': account_no,
                    'company_name':   company,
                    'total_owed':     past_due,
                    'past_due_amount': past_due,
                    'invoice_count':  1,
                    'bucket':         days_to_bucket(days_late),
                    'bucket_label':   days_to_bucket_label(days_late),
                    'status':         'pending',
                    'run_date':       today,
                    'last_invoice_date': last_inv or None,
                    'last_payment_date': last_pmt or None,
                    'days_old':       days_old,
                    'days_late':      days_late,
                })
            except Exception as e:
                print(f"    Row parse error: {e} — {row}")

        print(f"\n    AR records with past due balance: {len(ar_rows)}")
        for r in ar_rows[:5]:
            print(f"    {r['company_name']} ({r['account_number']}): ${r['past_due_amount']} — {r['bucket_label']}")

        # Save locally
        (OUT/'ar_scraper_last.json').write_text(json.dumps(ar_rows, indent=2))

        # Upsert to Supabase ar_collections
        if ar_rows:
            print(f"\n    Upserting {len(ar_rows)} rows to ar_collections...")
            r = requests.post(f'{SUPA}/rest/v1/ar_collections', headers=HDRS, json=ar_rows)
            print(f"    Supabase: {r.status_code}")
            if r.status_code >= 400:
                print(f"    Error: {r.text[:300]}")

        await br.close()
        print("    Done ✓")

asyncio.run(run())
