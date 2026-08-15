import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
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

        # Read render JS — this has the Kendo datasource URL
        print("[2] Reading render + profileFunctions JS files...")
        for js_file in [
            '/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_render.js',
            '/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_profileFunctions.js',
            '/Areas/Orders/Scripts/ReviewOrders/ReviewOrdersSubFrame_userActions.js',
        ]:
            js = await pg.evaluate(f"""async () => {{
                const r = await fetch('{js_file}');
                return await r.text();
            }}""")
            fname = js_file.split('/')[-1]
            print(f"\n  {fname}:")
            for line in js.split('\n'):
                s = line.strip()
                if s and any(x in s.lower() for x in ['url', 'api/', 'xapi', 'read', 'transport', 'schema', 'post', 'ajax', 'fetch', 'datasource', 'getorder', 'terminal']):
                    print(f"    {s[:160]}")
            # Save full file
            (OUT/fname).write_text(js)

        # Also load the subframe and wait for the grid to actually read data
        print("\n[3] Loading subframe and triggering grid read...")
        await pg.goto('https://www.goctl.com/orders/revieworders/reviewOrdersSubFrame', wait_until='load')
        await asyncio.sleep(8)  # wait longer for grid to initialize and fire read

        # Check what new requests fired
        order_apis = {url: body for url, body in captured.items()
                     if 'goctl.com' in url
                     and body.strip()[:1] in '[{'
                     and url not in [
                         'https://www.goctl.com/api/userbar/menu',
                         'https://www.goctl.com/api/profilecontrols/getemployeeprofile',
                     ]}
        print(f"    JSON APIs captured: {len(order_apis)}")
        for url, body in order_apis.items():
            path = url.split('goctl.com')[1][:100]
            # Focus on anything new/interesting
            if any(x in path.lower() for x in ['order', 'review', 'xapi', 'browse', 'grid', 'read', 'list', 'get']):
                print(f"\n  {path}")
                print(f"  {body[:300]}")

        print("\n[4] ALL unique API paths called:")
        paths = set(url.split('goctl.com')[1].split('?')[0] for url in captured if 'goctl.com' in url)
        for p in sorted(paths):
            print(f"  {p}")

        await br.close()

asyncio.run(run())
