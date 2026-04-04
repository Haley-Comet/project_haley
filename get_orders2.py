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
    captured_req = {}
    captured_resp = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_req(r):
            if 'GetReviewOrders' in r.url:
                try:
                    captured_req['url'] = r.url
                    captured_req['method'] = r.method
                    captured_req['headers'] = dict(r.headers)
                    captured_req['body'] = r.post_data
                    print(f"\n  *** CAPTURED REQUEST ***")
                    print(f"  URL: {r.url}")
                    print(f"  Method: {r.method}")
                    print(f"  Headers: {dict(r.headers)}")
                    print(f"  Body: {r.post_data}")
                except: pass

        async def on_resp(r):
            if 'GetReviewOrders' in r.url:
                try:
                    b = await r.text()
                    captured_resp['body'] = b
                    print(f"\n  *** CAPTURED RESPONSE ***")
                    print(f"  Status: {r.status}")
                    print(f"  Body: {b[:1000]}")
                    (OUT/'review_orders_real.json').write_text(b)
                except: pass

        pg.on('request', on_req)
        pg.on('response', on_resp)

        print("[1] Logging in...")
        await login(pg)

        # Go to the subframe directly
        print("[2] Loading subframe...")
        await pg.goto('https://www.goctl.com/orders/revieworders/reviewOrdersSubFrame', wait_until='load')
        await asyncio.sleep(5)

        # Now trigger the grid search — call checkGridReady with Comet terminal
        print("[3] Triggering grid search for Comet (terminal 22)...")
        result = await pg.evaluate("""async () => {
            try {
                // Set terminal to Comet (22)
                const termSelect = document.getElementById('Terminals');
                if (termSelect) {
                    // Try to set value to Comet
                    for (let opt of termSelect.options) {
                        opt.selected = opt.value === '22';
                    }
                    console.log('Terminal set to 22');
                }

                // Call checkGridReady to trigger the search
                if (typeof checkGridReady === 'function') {
                    checkGridReady(1, 0, 1);
                    return 'checkGridReady called';
                } else {
                    return 'checkGridReady not found — available: ' + Object.keys(window).filter(k => k.includes('Grid') || k.includes('grid') || k.includes('check')).join(', ');
                }
            } catch(e) {
                return 'error: ' + e.toString();
            }
        }""")
        print(f"    JS result: {result}")
        await asyncio.sleep(5)  # wait for API call

        if 'body' in captured_resp:
            print(f"\nSUCCESS — saved to /opt/xcelerator/output/review_orders_real.json")
        else:
            print("\nNo GetReviewOrders call captured. Trying form-encoded POST...")
            # Try form-encoded instead of JSON
            result2 = await pg.evaluate("""async () => {
                const body = new URLSearchParams({
                    Terminals: '22',
                    page: '1',
                    pageSize: '100',
                    skip: '0',
                    take: '100'
                });
                const r = await fetch('/api/revieworders/GetReviewOrders', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: body.toString()
                });
                return {status: r.status, body: (await r.text()).substring(0, 500)};
            }""")
            print(f"  Form-encoded: status={result2['status']} body={result2['body'][:200]}")

        await br.close()

asyncio.run(run())
