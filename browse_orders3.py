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
    known = {'/api/profilecontrols/getemployeeprofile','/api/userbar/menu',
             '/api/dashboard/getReportList','/api/controls/GetTerminals',
             '/api/dashboard/getcompanynews','/api/dashboard/gettotals',
             '/api/dashboard/getindustrynews','/api/dashboard/getkssnews',
             '/api/dashboard/getReportList'}

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
                    captured[key] = {'url': r.url, 'body': b[:5000]}
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")
        await pg.screenshot(path=str(SS/'b3_home.png'), full_page=True)

        # Dump the full left sidebar HTML to find Browse Orders link
        print("[2] Reading sidebar...")
        sidebar = await pg.evaluate("""() => {
            const nav = document.querySelector('nav, .sidebar, .side-menu, .nav-menu, [class*=sidebar], [class*=nav]');
            return nav ? nav.innerHTML.substring(0, 3000) : document.querySelector('body').innerHTML.substring(0, 3000);
        }""")
        (OUT/'sidebar.html').write_text(sidebar)
        print(f"    Sidebar HTML saved ({len(sidebar)} chars)")

        # Find all links containing 'browse' or 'order'
        links = await pg.evaluate("""() => {
            return Array.from(document.querySelectorAll('a, [onclick], [data-url]')).map(e => ({
                text: e.innerText.trim(),
                href: e.href || '',
                onclick: (e.getAttribute('onclick') || '').substring(0,100)
            })).filter(l => l.text.length > 0);
        }""")
        print(f"    All clickable elements: {len(links)}")
        for l in links:
            if any(x in l['text'].lower() for x in ['browse', 'order', 'dispatch', 'distribution', 'operation']):
                print(f"    MATCH: '{l['text']}' href={l['href'][:80]} onclick={l['onclick'][:60]}")

        # Try clicking Browse Orders directly
        print("\n[3] Clicking Browse Orders...")
        try:
            await pg.click('text=Browse Orders', timeout=5000)
            await asyncio.sleep(4)
            print(f"    URL after click: {pg.url}")
            await pg.screenshot(path=str(SS/'b3_after_click.png'), full_page=True)
        except Exception as e:
            print(f"    Could not click 'Browse Orders': {e}")
            # Try clicking Operations first, then Browse Orders
            try:
                await pg.click('text=Operations', timeout=3000)
                await asyncio.sleep(2)
                await pg.click('text=Browse Orders', timeout=3000)
                await asyncio.sleep(4)
                print(f"    URL after Operations > Browse: {pg.url}")
                await pg.screenshot(path=str(SS/'b3_ops_browse.png'), full_page=True)
            except Exception as e2:
                print(f"    Also failed via Operations: {e2}")

        # Show new APIs
        new_apis = {k:v for k,v in captured.items() if k not in known}
        print(f"\n[4] New APIs captured: {len(new_apis)}")
        for k, v in new_apis.items():
            print(f"\n  PATH: {k}")
            print(f"  URL:  {v['url']}")
            print(f"  BODY: {v['body'][:300]}")

        (OUT/'browse3.json').write_text(json.dumps({k: v['body'] for k,v in captured.items()}, indent=2))
        await br.close()
        print("\nDone")

asyncio.run(run())
