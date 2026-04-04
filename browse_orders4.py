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
                key = r.url.split('goctl.com')[1]
                captured[key] = b[:5000]
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)

        # Find what openFrame does — inspect the JS function
        print("[2] Reading openFrame function...")
        fn = await pg.evaluate("""() => {
            return typeof openFrame !== 'undefined' ? openFrame.toString() : 'NOT FOUND';
        }""")
        print(f"    openFrame: {fn[:500]}")

        # Also check what ReviewOrd maps to
        wm = await pg.evaluate("""() => {
            if (typeof WM_toggle !== 'undefined') return WM_toggle.toString().substring(0,300);
            const scripts = Array.from(document.querySelectorAll('script')).map(s=>s.innerHTML);
            const match = scripts.join('\\n').match(/ReviewOrd[^;]{0,200}/);
            return match ? match[0] : 'not found';
        }""")
        print(f"    ReviewOrd ref: {wm[:300]}")

        # Call openFrame('ReviewOrd') directly
        print("\n[3] Calling openFrame('ReviewOrd')...")
        await pg.evaluate("() => { openFrame('ReviewOrd'); }")
        await asyncio.sleep(5)
        await pg.screenshot(path=str(SS/'b4_after_openframe.png'), full_page=True)

        # Check for iframes
        frames = pg.frames
        print(f"    Frames active: {len(frames)}")
        for f in frames:
            print(f"    Frame URL: {f.url}")

        # Look for order data in captured responses
        print("\n[4] Captured URLs with order data...")
        for url, body in captured.items():
            if any(x in url.lower() for x in ['order','browse','review','dispatch']):
                if body.strip()[:1] in '[{':
                    print(f"\n  {url}")
                    print(f"  {body[:300]}")

        (OUT/'browse4_captured.json').write_text(json.dumps(captured, indent=2))
        print("\nAll captured URLs:")
        for url in captured.keys():
            print(f"  {url.split('?')[0]}")
        await br.close()

asyncio.run(run())
