import asyncio, os, json, re
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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await br.new_context(viewport={'width':1440,'height':900})
        pg = await ctx.new_page()
        pg.set_default_timeout(30000)

        captured = {}
        popup_captured = {}
        popup_pages = []

        async def on_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured[r.url] = json.loads(b)
            except: pass

        async def on_popup(popup):
            popup_pages.append(popup)
            print(f"  POPUP: {popup.url}")
            async def on_popup_resp(r):
                if 'goctl.com' not in r.url: return
                try:
                    b = await r.text()
                    if b.strip()[:1] in '[{':
                        popup_captured[r.url] = json.loads(b)
                    else:
                        popup_captured[r.url] = b[:300]
                except: pass
            popup.on('response', on_popup_resp)

        pg.on('response', on_resp)
        ctx.on('page', on_popup)
        await login(pg)
        print("Logged in.")

        # Dump ALL global vars that might be path/URL related
        globals_info = await pg.evaluate("""() => {
            const keys = Object.keys(window).filter(k => 
                typeof window[k] === 'string' && 
                (window[k].includes('goctl') || window[k].includes('Main') || window[k].includes('Client') || window[k].includes('/'))
                && window[k].length < 200
            );
            const result = {};
            keys.forEach(k => result[k] = window[k]);
            return result;
        }""")
        print(f"\n=== Relevant global vars ===")
        for k, v in globals_info.items():
            print(f"  {k} = {v}")

        # Try the ClientMaster click via the userBar_functions case statement
        # userBar_functions has: case 'ClientMaster':
        result = await pg.evaluate("""() => {
            const fns = Object.keys(window).filter(k => typeof window[k] === 'function');
            return fns.filter(k => k.toLowerCase().includes('client') || k.toLowerCase().includes('master'));
        }""")
        print(f"\n=== Client-related window functions ===")
        print(result)

        # Try to trigger ClientMaster the way userBar_functions does it
        # based on case 'ClientMaster': pattern
        print(f"\n=== Triggering ClientMaster via JS click on span ===")
        popup_pages.clear()
        popup_captured.clear()

        trigger_result = await pg.evaluate("""() => {
            const span = document.getElementById('ClientMaster');
            if (!span) return 'span not found';
            span.click();
            return 'clicked';
        }""")
        print(f"Click result: {trigger_result}")
        await asyncio.sleep(5)

        if popup_pages:
            pp = popup_pages[0]
            print(f"  URL: {pp.url}")
            await pp.wait_for_load_state('load', timeout=10000)
            api = [u for u in popup_captured if '/api/' in u]
            print(f"  API calls: {api[:10]}")
            for u in api[:5]:
                print(f"    {u}: {json.dumps(popup_captured[u])[:200]}")

            # Also check frames in popup
            frames = [f.url for f in pp.frames if f.url and f.url != 'about:blank']
            print(f"  Frames: {frames}")
        else:
            print("  No popup — checking new frames on main page")
            frames = [f.url for f in pg.frames if f.url and f.url != 'about:blank']
            print(f"  All frames: {frames}")
            new_api = [u for u in captured if 'client' in u.lower()]
            print(f"  Client API calls: {new_api}")

        await br.close()

asyncio.run(run())
