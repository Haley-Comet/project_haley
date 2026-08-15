import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']

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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_response(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured[r.url] = json.loads(b)
            except: pass

        pg.on('response', on_response)
        await login(pg)

        # Step 1: Print full menu to find invoice links
        menu_url = [u for u in captured if 'userbar/menu' in u]
        if menu_url:
            menu = captured[menu_url[0]]
            print("=== FULL MENU (Accounting section) ===")
            for cat in (menu.get('Data') or []):
                if cat.get('text') == 'Accounting':
                    print(json.dumps(cat, indent=2))

        # Step 2: Try candidate invoice URLs
        candidates = [
            'https://www.goctl.com/Main/Accounting/Invoices',
            'https://www.goctl.com/Main/Accounting/Invoice',
            'https://www.goctl.com/Main/Invoice/Index',
            'https://www.goctl.com/Main/Accounting/ApplyInvoice',
            'https://www.goctl.com/Main/AR/Index',
            'https://www.goctl.com/Main/Accounting/AR',
            'https://www.goctl.com/Main/Billing/Index',
        ]

        for url in candidates:
            captured_before = set(captured.keys())
            await pg.goto(url, wait_until='load')
            await asyncio.sleep(3)
            title = await pg.title()
            new_reqs = [u for u in captured if u not in captured_before and '/api/' in u]
            print(f"\n--- {url} ---")
            print(f"Title: {title}")
            print(f"New API calls: {new_reqs}")
            if 'UniversalException' not in pg.url and 'Error' not in title:
                print(f"  *** VALID PAGE: {pg.url}")
                html = await pg.content()
                print(f"  HTML snippet: {html[2000:3000]}")

        await br.close()

asyncio.run(run())
