import asyncio, os
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SS   = Path('/opt/xcelerator/screenshots')
OUT  = Path('/opt/xcelerator/output')

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("[1] Going to Main/home (triggers redirect to login)...")
        await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
        print(f"    On: {pg.url}")

        print("[2] Filling credentials...")
        await pg.type('input[name="UserName"]', USER, delay=50)
        await pg.type('input[name="Password"]', PASS, delay=50)

        print("[3] Submitting and waiting for load...")
        await pg.click('button[type="submit"]')
        await pg.wait_for_load_state('load')
        await asyncio.sleep(3)  # let JS render after load
        print(f"    Landed on: {pg.url}")

        # Screenshot + dump
        await pg.screenshot(path=str(SS/'test3_result.png'), full_page=True)
        text = await pg.inner_text('body')
        print(f"    Page text (first 400):\n{text[:400]}")

        # Save HTML for inspection
        (OUT/'test3_page.html').write_text(await pg.content())
        print("    HTML saved to /opt/xcelerator/output/test3_page.html")

        await br.close()

asyncio.run(run())
