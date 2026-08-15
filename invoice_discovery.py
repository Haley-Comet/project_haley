import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']

TEST_CLIENT_ID = 10016  # Kirkland & Ellis

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(6)

async def run():
    from playwright.async_api import async_playwright
    captured = {}
    all_requests = []

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_response(r):
            if 'goctl.com' not in r.url:
                return
            try:
                all_requests.append(r.url)
                b = await r.text()
                if b.strip()[:1] in '[{':
                    key = r.url
                    captured[key] = json.loads(b)
            except: pass

        pg.on('response', on_response)
        await login(pg)
        print(f"Logged in. Navigating to invoice page...")

        # Try the Apply_Invoice page
        url = f'https://www.goctl.com/Main/Apply_Invoice.aspx?ClientID={TEST_CLIENT_ID}'
        await pg.goto(url, wait_until='load')
        await asyncio.sleep(5)

        print(f"\n=== PAGE TITLE ===")
        print(await pg.title())

        print(f"\n=== ALL REQUESTS TO goctl.com ===")
        for r in all_requests:
            print(r)

        print(f"\n=== CAPTURED API RESPONSES ===")
        for url, data in captured.items():
            if 'goctl.com/Main/home' not in url and 'goctl.com/api/login' not in url:
                preview = json.dumps(data)[:300]
                print(f"\n--- {url} ---")
                print(preview)

        # Also dump page HTML for inspection
        html = await pg.content()
        # Look for table data or invoice numbers
        import re
        invoice_nums = re.findall(r'\b\d{4,6}_\d+_XPDF\b|\bInv\s*#?\s*\d+\b|invoice[_\s]?\d+', html, re.I)
        print(f"\n=== INVOICE PATTERNS IN HTML ===")
        print(invoice_nums[:20])

        # Look for any tables
        tables = await pg.query_selector_all('table')
        print(f"\n=== TABLES ON PAGE: {len(tables)} ===")
        for i, t in enumerate(tables[:3]):
            txt = await t.inner_text()
            print(f"Table {i}: {txt[:300]}")

        await br.close()

asyncio.run(run())
