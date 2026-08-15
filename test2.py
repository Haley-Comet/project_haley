import asyncio, os
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER  = os.environ['GOCTL_USER']
PASS  = os.environ['GOCTL_PASS']
SS    = Path('/opt/xcelerator/screenshots')

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        # Go to Main/home first — let it redirect to login
        print("[1] Navigating to Main/home (unauthenticated)...")
        await pg.goto('https://www.goctl.com/Main/home', wait_until='networkidle')
        print(f"    Redirected to: {pg.url}")
        await pg.screenshot(path=str(SS/'t2_01.png'), full_page=True)

        # Now we should be on a login page — fill it
        print("[2] Filling login form...")
        await pg.type('input[name="UserName"]', USER, delay=50)
        await pg.type('input[name="Password"]', PASS, delay=50)
        await pg.screenshot(path=str(SS/'t2_02.png'), full_page=True)

        print("[3] Submitting...")
        await pg.click('button[type="submit"]')
        await pg.wait_for_load_state('networkidle')
        print(f"    Landed on: {pg.url}")

        text = await pg.inner_text('body')
        print(f"    Page (first 300):\n{text[:300]}")
        await pg.screenshot(path=str(SS/'t2_03.png'), full_page=True)

        await br.close()

asyncio.run(run())
