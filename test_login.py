import asyncio, os
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
LOGIN = os.environ['GOCTL_URL']
print(f"Login URL: {LOGIN}")
print(f"Username:  {USER}")

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        print(f"[1] Going to {LOGIN}")
        await pg.goto(LOGIN, wait_until='networkidle')
        print(f"    Landed on: {pg.url}")
        await pg.type('input[name="UserName"]', USER, delay=50)
        await pg.type('input[name="Password"]', PASS, delay=50)
        await pg.click('button[type="submit"]')
        await pg.wait_for_load_state('networkidle')
        print(f"[2] After submit: {pg.url}")
        text = await pg.inner_text('body')
        print(f"    Page text (first 200): {text[:200]}")
        await pg.screenshot(path='/opt/xcelerator/screenshots/test_login.png', full_page=True)
        await br.close()

asyncio.run(run())
