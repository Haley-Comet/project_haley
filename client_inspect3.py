import asyncio, os, json, re
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
    await asyncio.sleep(5)

async def run():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        context = await br.new_context(viewport={'width':1440,'height':900})
        pg = await context.new_page()
        pg.set_default_timeout(30000)

        print("[1] Logging in...")
        await login(pg)

        # Open a NEW tab and navigate directly to client profile — full render
        print("\n[2] Opening client profile in new tab (full render)...")
        tab = await context.new_page()
        tab.set_default_timeout(30000)

        await tab.goto('https://www.goctl.com/Client/ClientMaster/ClientMasterBody.aspx?ClientID=3155&METHOD=GET',
                       wait_until='networkidle')
        await asyncio.sleep(3)
        await tab.screenshot(path=str(SS/'client_profile_full.png'), full_page=True)

        text = await tab.inner_text('body')
        print(f"\n[3] Rendered text for Kirkland (3155):\n{text[:1000]}")
        html = await tab.content()
        (OUT/'client_profile_full.html').write_text(html)

        # Try a few other known accounts
        print("\n[4] Testing a few more accounts...")
        for client_id, name in [('6030', 'ADP/Sodexo'), ('12692', 'Winston & Strawn'), ('5677', 'Affiliated Steam')]:
            await tab.goto(
                f'https://www.goctl.com/Client/ClientMaster/ClientMasterBody.aspx?ClientID={client_id}&METHOD=GET',
                wait_until='networkidle')
            await asyncio.sleep(2)
            text = await tab.inner_text('body')
            print(f"\n  Client {client_id} ({name}):")
            print(f"  {text[:400]}")

        await br.close()

asyncio.run(run())
