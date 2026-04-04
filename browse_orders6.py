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

        # Go directly to the subframe — this is where the grid lives
        print("[2] Loading reviewOrdersSubFrame directly...")
        await pg.goto('https://www.goctl.com/orders/revieworders/reviewOrdersSubFrame', wait_until='load')
        await asyncio.sleep(6)
        print(f"    URL: {pg.url}")
        await pg.screenshot(path=str(SS/'ro_subframe.png'), full_page=True)

        # Read the config JS to find the datasource URL
        print("\n[3] Reading subframe config JS...")
        for js_file in [
            '/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_config.js',
            '/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_gridFunctions.js',
        ]:
            js = await pg.evaluate(f"""async () => {{
                const r = await fetch('{js_file}');
                return await r.text();
            }}""")
            print(f"\n  {js_file}:")
            for line in js.split('\n'):
                if any(x in line.lower() for x in ['url', 'api/', 'xapi', 'read', 'transport', 'data', 'ajax', 'fetch', 'getorder', 'post']):
                    print(f"    {line.strip()[:150]}")

        # Show all captured API calls
        print("\n[4] All captured JSON API calls:")
        for url, body in captured.items():
            if body.strip()[:1] in '[{' and '/api/' in url:
                path = url.split('goctl.com')[1][:80]
                print(f"\n  {path}")
                print(f"  {body[:250]}")

        (OUT/'ro_subframe_captured.json').write_text(json.dumps(captured, indent=2))
        print("\nSaved to /opt/xcelerator/output/ro_subframe_captured.json")
        await br.close()

asyncio.run(run())
