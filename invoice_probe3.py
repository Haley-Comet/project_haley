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
        print("Logged in. Looking for Invoicing menu item...")

        # Wait for menu to be ready
        await asyncio.sleep(3)

        # Try clicking the Accounting menu, then Invoicing
        try:
            # Hover over Accounting to reveal submenu
            acct = await pg.query_selector('#Accounting, [id="Accounting"], span:has-text("Accounting")')
            if acct:
                await acct.hover()
                await asyncio.sleep(1)
                print("Hovered over Accounting")
            
            # Click Invoicing
            inv = await pg.query_selector('#Invoicing, [id="Invoicing"], span:has-text("Invoicing")')
            if inv:
                before = set(captured.keys())
                await inv.click()
                await asyncio.sleep(5)
                new_reqs = [u for u in captured if u not in before]
                print(f"\n=== NEW API CALLS AFTER CLICKING INVOICING ===")
                for u in new_reqs:
                    print(u)
                    print(json.dumps(captured[u])[:400])
                    print()
            else:
                print("Invoicing element not found, trying by text...")
                # Try finding by text content
                elements = await pg.query_selector_all('span, a, li')
                for el in elements:
                    txt = await el.inner_text()
                    if txt.strip() == 'Invoicing':
                        print(f"Found: {await el.get_attribute('id')} / {await el.get_attribute('class')}")
                        before = set(captured.keys())
                        await el.click()
                        await asyncio.sleep(5)
                        new_reqs = [u for u in captured if u not in before]
                        print("New API calls:", new_reqs)
                        for u in new_reqs:
                            print(u)
                            print(json.dumps(captured[u])[:400])
                        break
        except Exception as e:
            print(f"Click error: {e}")

        # Also check current page URL and iframes
        print(f"\n=== CURRENT URL: {pg.url} ===")
        frames = pg.frames
        print(f"=== FRAMES ({len(frames)}) ===")
        for f in frames:
            print(f"  Frame URL: {f.url}")

        await br.close()

asyncio.run(run())
