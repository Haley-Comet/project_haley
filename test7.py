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
    await asyncio.sleep(4)

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(15000)

        # Capture API responses
        api_responses = {}
        async def handle_response(response):
            url = response.url
            if '/api/' in url and 'goctl.com' in url:
                try:
                    body = await response.text()
                    api_responses[url] = body[:500]
                except: pass
        pg.on('response', handle_response)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")
        await asyncio.sleep(3)  # let all API calls fire

        # Print captured API calls
        print(f"\n[2] API calls captured: {len(api_responses)}")
        for url, body in api_responses.items():
            print(f"\n  URL: {url}")
            print(f"  Response: {body[:200]}")

        (OUT/'api_responses.json').write_text(json.dumps(api_responses, indent=2))

        # Call the menu API directly to get navigation structure
        print("\n[3] Calling menu API...")
        import time
        ts = int(time.time() * 1000)
        menu_resp = await pg.evaluate(f"""async () => {{
            const r = await fetch('/api/userbar/menu?_={ts}');
            return await r.text();
        }}""")
        print(f"    Menu response: {menu_resp[:500]}")
        (OUT/'menu_api.json').write_text(menu_resp)

        # Try order-related API endpoints
        print("\n[4] Probing order APIs...")
        order_apis = [
            '/api/orders/active',
            '/api/orders/list',
            '/api/dispatch/orders',
            '/api/dispatch/active',
            '/api/activeorders',
            '/api/orderoverview',
            '/api/erdereoverview',
            '/api/distribution/orders',
            '/api/operations/orders',
            '/api/orders',
            '/api/dispatch',
        ]
        for path in order_apis:
            try:
                result = await pg.evaluate(f"""async () => {{
                    const r = await fetch('{path}?_={ts}');
                    return {{status: r.status, body: (await r.text()).substring(0, 200)}};
                }}""")
                if result['status'] < 400:
                    print(f"    ✓ {path} → {result['status']}: {result['body'][:100]}")
                    (OUT/f"api_{path.replace('/','_').strip('_')}.json").write_text(result['body'])
                else:
                    print(f"    ✗ {path} → {result['status']}")
            except Exception as e:
                print(f"    ✗ {path} → error: {e}")

        await br.close()

asyncio.run(run())
