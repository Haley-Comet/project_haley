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

        print("[2] Going to /Main/browse...")
        await pg.goto('https://www.goctl.com/Main/browse', wait_until='load')
        await asyncio.sleep(5)
        print(f"    URL: {pg.url}")
        await pg.screenshot(path=str(SS/'browse_main.png'), full_page=True)

        # Filter out noise APIs we already know about
        known = {'/api/profilecontrols/getemployeeprofile','/api/userbar/menu',
                 '/api/dashboard/getReportList','/api/controls/GetTerminals',
                 '/api/dashboard/getcompanynews','/api/dashboard/gettotals',
                 '/api/dashboard/getindustrynews','/api/dashboard/getkssnews'}

        new_apis = {k:v for k,v in captured.items() if k not in known}
        print(f"\n    New APIs captured: {len(new_apis)}")
        for k, v in new_apis.items():
            print(f"\n  PATH: {k}")
            print(f"  FULL URL: {v['url']}")
            print(f"  BODY: {v['body'][:300]}")

        (OUT/'browse_orders2.json').write_text(json.dumps({k: v['body'] for k,v in captured.items()}, indent=2))
        print("\nSaved to /opt/xcelerator/output/browse_orders2.json")
        await br.close()

asyncio.run(run())
