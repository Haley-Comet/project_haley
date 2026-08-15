import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(8)

async def run():
    from playwright.async_api import async_playwright
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_response(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured[r.url] = json.loads(b)
            except: pass

        pg.on('response', on_response)
        await login(pg)
        print("Logged in.")
        before = set(captured.keys())

        # Try triggering the Invoicing menu item via JavaScript
        # The span has id='Invoicing' - try clicking it via JS
        try:
            result = await pg.evaluate("""
                () => {
                    // Try finding the span by ID and clicking it
                    const el = document.getElementById('Invoicing');
                    if (el) {
                        el.click();
                        return 'clicked #Invoicing';
                    }
                    // Try finding by text
                    const spans = document.querySelectorAll('span');
                    for (const s of spans) {
                        if (s.textContent.trim() === 'Invoicing') {
                            s.click();
                            return 'clicked span Invoicing text';
                        }
                    }
                    return 'not found';
                }
            """)
            print(f"JS result: {result}")
        except Exception as e:
            print(f"JS eval error: {e}")

        await asyncio.sleep(5)
        new_reqs = [u for u in captured if u not in before]
        print(f"\n=== NEW API CALLS AFTER JS CLICK ===")
        for u in new_reqs:
            print(u)

        # Check what frames loaded
        print(f"\n=== FRAME URLs AFTER CLICK ===")
        for f in pg.frames:
            if f.url != 'about:blank' and 'goctl.com' in f.url:
                print(f"  {f.url}")

        # Try a different approach - look at what JS functions exist
        funcs = await pg.evaluate("""
            () => {
                const keys = [];
                for (const k in window) {
                    if (typeof window[k] === 'function' && 
                        (k.toLowerCase().includes('window') || 
                         k.toLowerCase().includes('open') ||
                         k.toLowerCase().includes('load') ||
                         k.toLowerCase().includes('menu'))) {
                        keys.push(k);
                    }
                }
                return keys.slice(0, 30);
            }
        """)
        print(f"\n=== WINDOW FUNCTIONS (load/open/menu) ===")
        print(funcs)

        # Try calling common Xcelerator window functions
        for fn in ['OpenWindow', 'openWindow', 'LoadWindow', 'loadWindow', 'OpenPage', 'showModule']:
            try:
                r = await pg.evaluate(f"() => typeof {fn} !== 'undefined' ? {fn}.toString().slice(0,200) : 'not found'")
                if r != 'not found':
                    print(f"\n=== {fn} FOUND ===")
                    print(r)
            except: pass

        await br.close()

asyncio.run(run())
