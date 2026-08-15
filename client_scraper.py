import asyncio, os, json, requests, re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

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

def parse_client_html(html, client_id, client_name):
    """Parse ClientMasterBody.aspx HTML for account fields."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator='\n')
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        def find_after(label, lines, window=3):
            for i, l in enumerate(lines):
                if label.lower() in l.lower():
                    for j in range(1, window+1):
                        if i+j < len(lines) and lines[i+j] and lines[i+j].lower() != label.lower():
                            return lines[i+j]
            return None

        # Try to find account number
        acct_match = re.search(r'Account\s*(?:No|Number|#)[:\s]*(\d+)', text, re.I)
        acct_no = int(acct_match.group(1)) if acct_match else None

        # Address fields
        street = find_after('Address', lines)
        city_state = find_after('City', lines) or find_after('City/State', lines)
        phone = find_after('Phone', lines)
        email_match = re.search(r'[\w\.\-]+@[\w\.\-]+\.\w+', text)
        email = email_match.group(0) if email_match else None
        contact = find_after('Contact', lines)
        terms = find_after('Terms', lines)

        # Parse city/state/zip
        city, state, zip_code = None, None, None
        if city_state:
            m = re.match(r'^([^,]+),\s*([A-Z]{2})\s*(\d{5})?', city_state)
            if m:
                city = m.group(1).strip()
                state = m.group(2)
                zip_code = m.group(3)

        return {
            'account_number': acct_no,
            'company_name': client_name,
            'contact_name': contact,
            'phone': phone,
            'email': email,
            'street': street,
            'city': city,
            'state': state,
            'zip_code': zip_code,
            'terms': terms,
            'status': 'active',
            'last_synced_at': datetime.utcnow().isoformat(),
        }
    except Exception as e:
        return None

async def fetch_client(context, client_id, client_name, semaphore):
    """Fetch a single client profile."""
    async with semaphore:
        try:
            page = await context.new_page()
            page.set_default_timeout(15000)
            resp = await page.goto(
                f'https://www.goctl.com/Client/ClientMaster/ClientMasterBody.aspx?ClientID={client_id}&METHOD=GET',
                wait_until='domcontentloaded'
            )
            await asyncio.sleep(0.5)
            html = await page.content()
            await page.close()

            parsed = parse_client_html(html, client_id, client_name)
            return parsed
        except Exception as e:
            try: await page.close()
            except: pass
            return None

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now()
    print(f"[{now.strftime('%H:%M:%S')}] Client Scraper starting...")

    # Load client list
    clients_file = OUT/'clients_list.json'
    if not clients_file.exists():
        print("ERROR: clients_list.json not found — run client_discovery6.py first")
        return
    clients = json.loads(clients_file.read_text())
    print(f"    {len(clients)} clients to process")

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])

        # Login on main page to establish session
        pg = await br.new_page()
        pg.set_default_timeout(30000)
        print("    Logging in...")
        await login(pg)
        await pg.close()

        # Use the same browser context (session cookies are shared)
        context = pg.context
        semaphore = asyncio.Semaphore(5)  # 5 concurrent requests

        # Process in batches
        results = []
        batch_size = 50
        for i in range(0, len(clients), batch_size):
            batch = clients[i:i+batch_size]
            tasks = [fetch_client(context, c['id'], c['name'], semaphore) for c in batch]
            batch_results = await asyncio.gather(*tasks)
            good = [r for r in batch_results if r and r.get('account_number')]
            results.extend(good)
            print(f"    Batch {i//batch_size+1}: {len(good)}/{len(batch)} parsed (total: {len(results)})")

            # Sample first result
            if i == 0 and good:
                print(f"    Sample: {json.dumps(good[0], indent=2)}")

        print(f"\n    Total parsed: {len(results)}")

        # Upsert to Supabase in chunks
        if results:
            print(f"    Upserting to Supabase...")
            ok = 0
            for j in range(0, len(results), 50):
                chunk = results[j:j+50]
                r = requests.post(f'{SUPA}/rest/v1/client_accounts', headers=HDRS, json=chunk)
                if r.status_code in (200, 201):
                    ok += len(chunk)
                else:
                    print(f"    Chunk error {r.status_code}: {r.text[:200]}")
            print(f"    Upserted {ok} rows")

        (OUT/'client_scraper_sample.json').write_text(json.dumps(results[:5], indent=2))
        await br.close()
        print("    Done ✓")

asyncio.run(run())
