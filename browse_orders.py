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
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    key = r.url.split('goctl.com')[1].split('?')[0]
                    captured[key] = {'url': r.url, 'body': b[:3000]}
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")

        print("[2] Navigating to Browse Orders...")
        # Try clicking through the UI like a human
        await pg.goto('https://www.goctl.com/Main/Distribution/BrowseOrders', wait_until='load')
        await asyncio.sleep(3)
        print(f"    URL: {pg.url}")
        await pg.screenshot(path=str(SS/'browse_01.png'), full_page=True)

        print(f"    APIs captured so far: {len(captured)}")
        for k, v in captured.items():
            print(f"\n  {k}")
            print(f"  {v['body'][:150]}")

        # If that failed, try Operations
        if 'browse' not in pg.url.lower() and 'order' not in pg.url.lower():
            print("\n[3] Trying Operations/BrowseOrders...")
            await pg.goto('https://www.goctl.com/Main/Operations/BrowseOrders', wait_until='load')
            await asyncio.sleep(3)
            print(f"    URL: {pg.url}")
            await pg.screenshot(path=str(SS/'browse_02.png'), full_page=True)
            print(f"    APIs captured: {len(captured)}")
            for k, v in captured.items():
                if k not in ['/api/profilecontrols/getemployeeprofile','/api/userbar/menu']:
                    print(f"\n  {k}")
                    print(f"  {v['body'][:150]}")

        OUT.mkdir(exist_ok=True)
        (OUT/'browse_captured.json').write_text(json.dumps({k: v['body'] for k,v in captured.items()}, indent=2))
        print("\nSaved to /opt/xcelerator/output/browse_captured.json")
        await br.close()

asyncio.run(run())
