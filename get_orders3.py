import asyncio, os, json
from pathlib import Path

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
    await asyncio.sleep(6)

async def run():
    from playwright.async_api import async_playwright
    captured_req = None
    captured_resp = None

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_req(r):
            nonlocal captured_req
            if 'GetReviewOrders' in r.url:
                captured_req = {
                    'url': r.url,
                    'method': r.method,
                    'body': r.post_data,
                    'headers': dict(r.headers)
                }
                print(f"\n*** INTERCEPTED REQUEST ***")
                print(f"  Body: {r.post_data}")

        async def on_resp(r):
            nonlocal captured_resp
            if 'GetReviewOrders' in r.url:
                try:
                    b = await r.text()
                    captured_resp = b
                    print(f"\n*** INTERCEPTED RESPONSE ***")
                    print(f"  Status: {r.status}")
                    print(f"  Body (first 500): {b[:500]}")
                    (OUT/'review_orders_real.json').write_text(b)
                except: pass

        pg.on('request', on_req)
        pg.on('response', on_resp)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")
        await pg.screenshot(path=str(SS/'go3_home.png'), full_page=True)

        # Open the Review Orders frame from the main page — exactly like Jim
        print("\n[2] Opening Review Orders frame...")
        result = await pg.evaluate("() => { openFrame('ReviewOrd'); return 'called'; }")
        print(f"    openFrame: {result}")

        # Wait for the iframe to load and fire the API
        print("    Waiting for grid to load (15 seconds)...")
        await asyncio.sleep(15)

        # Find the review orders frame
        ro_frame = None
        for frame in pg.frames:
            if 'revieworders' in frame.url.lower() and 'subframe' not in frame.url.lower():
                ro_frame = frame
                print(f"    Found RO frame: {frame.url}")

        sub_frame = None
        for frame in pg.frames:
            if 'reviewOrdersSubFrame' in frame.url:
                sub_frame = frame
                print(f"    Found subframe: {frame.url}")

        await pg.screenshot(path=str(SS/'go3_after_open.png'), full_page=True)

        if sub_frame:
            print(f"\n[3] Subframe found — checking for grid data...")
            # Try calling checkGridReady inside the subframe context
            r = await sub_frame.evaluate("""() => {
                try {
                    const fns = Object.keys(window).filter(k =>
                        typeof window[k] === 'function' &&
                        (k.includes('Grid') || k.includes('grid') || k.includes('check') || k.includes('Review'))
                    );
                    return 'Functions: ' + fns.join(', ');
                } catch(e) { return 'error: ' + e; }
            }""")
            print(f"    Subframe functions: {r}")

            # Try setting terminal and calling checkGridReady in subframe
            r2 = await sub_frame.evaluate("""() => {
                try {
                    if (typeof checkGridReady === 'function') {
                        // Try Kendo multiselect
                        const ms = $('#Terminals').data('kendoMultiSelect');
                        if (ms) {
                            ms.value(['22']);
                            ms.trigger('change');
                        }
                        checkGridReady(1, 0, 1);
                        return 'checkGridReady called';
                    }
                    return 'checkGridReady not found';
                } catch(e) { return 'error: ' + e; }
            }""")
            print(f"    checkGridReady result: {r2}")
            await asyncio.sleep(8)

        if captured_resp:
            data = json.loads(captured_resp)
            print(f"\n=== SUCCESS ===")
            if isinstance(data, dict) and 'Data' in data:
                rows = data['Data']
                print(f"Orders returned: {len(rows)}")
                if rows:
                    print(f"First order keys: {list(rows[0].keys())}")
                    print(f"First order: {json.dumps(rows[0], indent=2)[:500]}")
            else:
                print(f"Response: {str(data)[:300]}")
        else:
            print("\nNo GetReviewOrders response captured")
            print(f"Request captured: {captured_req is not None}")

        await br.close()

asyncio.run(run())
