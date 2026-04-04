import asyncio, os, json
from pathlib import Path
from datetime import datetime

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
OUT  = Path('/opt/xcelerator/output')
SS   = Path('/opt/xcelerator/screenshots')

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(5)

async def run():
    from playwright.async_api import async_playwright
    req_bodies = {}
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        # Capture both request bodies AND responses
        async def on_request(r):
            if 'GetReviewOrders' in r.url or 'revieworders' in r.url.lower():
                try:
                    body = r.post_data
                    req_bodies[r.url] = body
                    print(f"\n  >>> REQUEST to {r.url.split('goctl.com')[1]}")
                    print(f"      Body: {body[:500] if body else 'empty'}")
                except: pass

        async def on_response(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:8000]
                if 'revieworders' in r.url.lower() or 'GetReview' in r.url:
                    print(f"\n  >>> RESPONSE from {r.url.split('goctl.com')[1][:80]}")
                    print(f"      {b[:400]}")
            except: pass

        pg.on('request', on_request)
        pg.on('response', on_response)

        print("[1] Logging in...")
        await login(pg)

        # Load the subframe
        print("\n[2] Loading reviewOrdersSubFrame...")
        await pg.goto('https://www.goctl.com/orders/revieworders/reviewOrdersSubFrame', wait_until='load')
        await asyncio.sleep(3)

        # Try to POST directly using page.evaluate — same session cookies apply
        print("\n[3] Calling GetReviewOrders directly with Comet terminal (22)...")
        today = datetime.now().strftime('%m/%d/%Y')

        # Try multiple body formats
        bodies = [
            # Format 1: minimal
            {"Terminals": "22", "Page": 1, "PageSize": 100},
            # Format 2: with dates
            {"Terminals": "22", "FromDate": today, "ToDate": today, "Page": 1, "PageSize": 100},
            # Format 3: all terminals
            {"Terminals": "0", "Page": 1, "PageSize": 50},
            # Format 4: status filter
            {"Terminals": "22", "Status": "N,R", "Page": 1, "PageSize": 100},
            # Format 5: empty body
            {},
        ]

        for i, body in enumerate(bodies):
            result = await pg.evaluate(f"""async () => {{
                try {{
                    const r = await fetch('/api/revieworders/GetReviewOrders', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({json.dumps(body)})
                    }});
                    const text = await r.text();
                    return {{status: r.status, body: text.substring(0, 500)}};
                }} catch(e) {{ return {{status: 0, body: e.toString()}}; }}
            }}""")
            print(f"\n  Body {i+1}: {json.dumps(body)[:80]}")
            print(f"  Status: {result['status']}")
            print(f"  Response: {result['body'][:300]}")
            if result['status'] == 200 and result['body'].strip()[:1] in '[{':
                (OUT/f'review_orders_body{i+1}.json').write_text(result['body'])
                print(f"  *** SAVED to review_orders_body{i+1}.json ***")

        await br.close()

asyncio.run(run())
