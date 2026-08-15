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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:5000]
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)

        # Open AcctRec
        print("\n[2] Opening AcctRec...")
        await pg.evaluate("() => { openFrame('AcctRec'); }")
        await asyncio.sleep(6)

        # Find AcctRec frame and load a known account
        acct_frame = next((f for f in pg.frames if 'AcctRec.aspx' in f.url), None)
        panel_frame = next((f for f in pg.frames if 'Panel.aspx' in f.url and 'AcctRec' in f.url), None)

        if acct_frame:
            print(f"    AcctRec frame found")

            # Try loading account 10016 (Kirkland & Ellis)
            print("    Loading account 10016 (Kirkland & Ellis)...")
            before = set(captured.keys())
            await acct_frame.fill('input[name="AccountNo"]', '10016')
            await pg.keyboard.press('Enter')
            await asyncio.sleep(4)
            await pg.screenshot(path=str(SS/'acct_rec_loaded.png'), full_page=True)

            new_keys = set(captured.keys()) - before
            print(f"    New responses: {len(new_keys)}")
            for k in new_keys:
                body = captured[k]
                if body.strip()[:1] in '[{':
                    print(f"\n    API: {k.split('goctl.com')[1][:80]}")
                    print(f"    {body[:300]}")
                else:
                    print(f"\n    Page: {k.split('goctl.com')[1][:80]} ({len(body)} chars)")

            # Get all frames after loading
            print("\n    Frames after loading account:")
            for frame in pg.frames:
                if 'goctl.com' in frame.url and 'Main/Home' not in frame.url:
                    print(f"      {frame.url}")
                    try:
                        text = await frame.inner_text('body')
                        if text.strip():
                            print(f"      Text: {text[:200]}")
                    except: pass

        # Now check Collections.aspx
        print("\n[3] Opening Collections frame...")
        await pg.evaluate("() => { openFrame('Collections'); }")
        await asyncio.sleep(6)

        coll_frame = next((f for f in pg.frames if 'Collections.aspx' in f.url), None)
        coll_panel = next((f for f in pg.frames if 'Panel.aspx' in f.url and 'Collections' in f.url), None)

        if coll_frame:
            print(f"    Collections.aspx found")
            text = await coll_frame.inner_text('body')
            print(f"    Text: {text[:500]}")
            html = await coll_frame.content()
            (OUT/'collections.html').write_text(html)

            inputs = await coll_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('input,select,button')).map(e=>({
                    name: e.name, id: e.id, type: e.type,
                    value: (e.value||'').substring(0,30), text: e.innerText
                }))
            """)
            print(f"    Inputs: {json.dumps(inputs[:10], indent=2)}")

        if coll_panel:
            print(f"\n    Collections Panel found")
            text = await coll_panel.inner_text('body')
            print(f"    Panel text: {text[:400]}")
            html = await coll_panel.content()
            (OUT/'collections_panel.html').write_text(html)

        # Also try StandardRep
        print("\n[4] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(5)
        std_frame = next((f for f in pg.frames if 'StandardRep' in f.url or 'standard' in f.url.lower()), None)
        if std_frame:
            print(f"    Found: {std_frame.url}")
            text = await std_frame.inner_text('body')
            print(f"    Text: {text[:400]}")

        await br.close()

asyncio.run(run())
