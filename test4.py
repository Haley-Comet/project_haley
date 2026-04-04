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

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(3)

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")

        # Dump all links from Main/home
        links = await pg.evaluate("""() => Array.from(document.querySelectorAll('a')).map(e=>({
            text: e.innerText.trim().replace(/\s+/g,' '),
            href: e.href
        })).filter(l=>l.text && l.href && !l.href.startsWith('javascript'))""")
        (OUT/'main_home_links.json').write_text(__import__('json').dumps(links, indent=2))
        print(f"    Links found: {len(links)}")
        for l in links: print(f"      {l['text']} → {l['href']}")

        # Try Operations section — likely has active orders
        print("\n[2] Trying Operations...")
        await pg.goto('https://www.goctl.com/Main/Operations', wait_until='load')
        await asyncio.sleep(2)
        print(f"    URL: {pg.url}")
        text = await pg.inner_text('body')
        print(f"    Text: {text[:300]}")
        await pg.screenshot(path=str(SS/'t4_operations.png'), full_page=True)

        # Try Distribution section
        print("\n[3] Trying Distribution...")
        await pg.goto('https://www.goctl.com/Main/Distribution', wait_until='load')
        await asyncio.sleep(2)
        print(f"    URL: {pg.url}")
        text = await pg.inner_text('body')
        print(f"    Text: {text[:300]}")
        await pg.screenshot(path=str(SS/'t4_distribution.png'), full_page=True)

        await br.close()

asyncio.run(run())
