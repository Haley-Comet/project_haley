import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
URL  = os.environ.get('GOCTL_URL', 'https://www.goctl.com/account/Account/login')
SS   = Path('/opt/xcelerator/screenshots')
OUT  = Path('/opt/xcelerator/output')
OUT.mkdir(exist_ok=True)

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("[1] Loading login page...")
        await pg.goto(URL, wait_until='networkidle')
        await pg.screenshot(path=str(SS/'01_login.png'), full_page=True)
        inputs = await pg.evaluate("() => Array.from(document.querySelectorAll('input')).map(e=>({name:e.name,id:e.id,type:e.type,placeholder:e.placeholder}))")
        print(f"    Inputs: {json.dumps(inputs)}")
        (OUT/'inputs.json').write_text(json.dumps(inputs, indent=2))

        print("[2] Filling form...")
        for sel in ['input[name="UserName"]','input[name="username"]','#UserName','input[type="text"]']:
            try:
                el = await pg.query_selector(sel)
                if el and await el.is_visible(): await el.fill(USER); print(f"    user: {sel}"); break
            except: pass
        for sel in ['input[name="Password"]','input[name="password"]','#Password','input[type="password"]']:
            try:
                el = await pg.query_selector(sel)
                if el and await el.is_visible(): await el.fill(PASS); print(f"    pass: {sel}"); break
            except: pass

        print("[3] Submitting...")
        clicked = False
        for sel in ['input[type="submit"]','button[type="submit"]','input[value="Login"]','button:has-text("Login")']:
            try:
                el = await pg.query_selector(sel)
                if el: await el.click(); clicked=True; print(f"    via: {sel}"); break
            except: pass
        if not clicked: await pg.keyboard.press('Enter'); print("    via Enter")

        await pg.wait_for_load_state('networkidle')
        await pg.screenshot(path=str(SS/'03_post_login.png'), full_page=True)
        print(f"    Post-login URL: {pg.url}")
        (OUT/'post_login_url.txt').write_text(pg.url)

        print("[4] Saving nav links...")
        links = await pg.evaluate("() => Array.from(document.querySelectorAll('a')).map(e=>({text:e.innerText.trim().replace(/\\s+/g,' '),href:e.href})).filter(l=>l.text&&l.href&&!l.href.startsWith('javascript'))")
        (OUT/'nav_links.json').write_text(json.dumps(links[:80], indent=2))
        (OUT/'main_page.html').write_text(await pg.content())
        print(f"    {len(links)} links saved")

        print("[5] Probing dispatch URLs...")
        base = 'https://www.goctl.com'
        found = []
        for path in ['/Online/Dispatch','/Online/Orders','/Online/OrderManagement','/Online/ActiveOrders','/Dispatch','/Orders','/Online','/Online/Home']:
            try:
                r = await pg.goto(base+path, wait_until='domcontentloaded', timeout=8000)
                if r and r.status < 400 and URL not in pg.url:
                    print(f"    OK: {pg.url}")
                    found.append(pg.url)
                    slug = path.replace('/','_').strip('_')
                    await pg.screenshot(path=str(SS/f'05_{slug}.png'), full_page=True)
                    (OUT/f'page_{slug}.html').write_text(await pg.content())
            except: pass
        (OUT/'found_pages.json').write_text(json.dumps(found, indent=2))

        print("\n=== DONE ===")
        print("Run this next:")
        print("  cat /opt/xcelerator/output/post_login_url.txt")
        print("  cat /opt/xcelerator/output/nav_links.json")
        await br.close()

asyncio.run(run())
