import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SS   = Path('/opt/xcelerator/screenshots')
OUT  = Path('/opt/xcelerator/output')

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(5)

async def run():
    from playwright.async_api import async_playwright
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:8000]
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)

        # Read the config JS file directly - it has the API endpoint
        print("[2] Reading ReviewOrdersSubFrame_config.js...")
        config_js = await pg.evaluate("""async () => {
            const r = await fetch('/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_config.js');
            return await r.text();
        }""")
        (OUT/'ro_config.js').write_text(config_js)
        # Print lines with api/url/endpoint
        for line in config_js.split('\n'):
            if any(x in line.lower() for x in ['api', 'url', 'endpoint', 'getorder', 'read', 'datasource', 'transport']):
                print(f"  {line.strip()[:150]}")

        print("\n[3] Reading ReviewOrders.js...")
        ro_js = await pg.evaluate("""async () => {
            const r = await fetch('/Areas/Orders/Scripts/ReviewOrders/ReviewOrders.js');
            return await r.text();
        }""")
        (OUT/'ro_main.js').write_text(ro_js)
        for line in ro_js.split('\n'):
            if any(x in line.lower() for x in ['api/', 'url:', 'endpoint', 'getorder', 'ajax', 'fetch', 'datasource']):
                print(f"  {line.strip()[:150]}")

        # Now navigate to the revieworders page directly and capture APIs
        print("\n[4] Loading revieworders directly...")
        await pg.goto('https://www.goctl.com/orders/revieworders', wait_until='load')
        await asyncio.sleep(5)
        print(f"    URL: {pg.url}")
        await pg.screenshot(path=str(SS/'ro_direct.png'), full_page=True)

        # Get all new API calls
        order_calls = {url: body for url, body in captured.items()
                      if 'goctl.com' in url and '/api/' in url
                      and body.strip()[:1] in '[{'}
        print(f"\n[5] JSON API calls captured: {len(order_calls)}")
        for url, body in order_calls.items():
            print(f"\n  {url.split('goctl.com')[1][:80]}")
            print(f"  {body[:200]}")

        await br.close()
        print("\nDone — check /opt/xcelerator/output/ro_config.js")

asyncio.run(run())
