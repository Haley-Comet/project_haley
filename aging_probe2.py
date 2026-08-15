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
    captured_reqs = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:8000]
            except: pass

        async def cap_req(r):
            if 'goctl.com' not in r.url: return
            if r.method == 'POST':
                try:
                    captured_reqs[r.url] = r.post_data or ''
                except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        # Read scripts.js - this has all the API calls
        print("\n[2] Reading SCRIPTS/scripts.js...")
        scripts_js = await pg.evaluate("""async () => {
            const r = await fetch('/SCRIPTS/scripts.js');
            return await r.text();
        }""")
        (OUT/'scripts_js.js').write_text(scripts_js)
        print(f"    scripts.js: {len(scripts_js)} chars")
        print("    Lines with api/ajax/url/aging/aging/ar:")
        for line in scripts_js.split('\n'):
            s = line.strip()
            if s and any(x in s.lower() for x in ['api/', 'ajax', 'url:', '.ajax', 'aging', 'getaging', 'getbalance', 'getclient', 'getinvoice', 'arreport', 'acctbalance']):
                print(f"    {s[:160]}")

        # Open AcctRec frame and wait
        print("\n[3] Opening AcctRec frame...")
        await pg.evaluate("() => { openFrame('AcctRec'); }")
        await asyncio.sleep(8)
        await pg.screenshot(path=str(SS/'acct_rec_open.png'), full_page=True)

        # Find the AcctRec frames
        acct_frame = None
        panel_frame = None
        for frame in pg.frames:
            if 'AcctRec.aspx' in frame.url:
                acct_frame = frame
            if 'Panel.aspx' in frame.url and 'AcctRec' in frame.url:
                panel_frame = frame

        if acct_frame:
            print(f"    AcctRec.aspx frame found: {acct_frame.url}")

            # Dump the page content
            html = await acct_frame.content()
            (OUT/'acct_rec.html').write_text(html)
            print(f"    HTML saved ({len(html)} chars)")

            # Get text content
            text = await acct_frame.inner_text('body')
            print(f"    Page text (first 500):\n{text[:500]}")

            # Find all form elements and hidden fields
            forms = await acct_frame.evaluate("""() => {
                return {
                    inputs: Array.from(document.querySelectorAll('input,select')).map(e=>({
                        name: e.name, id: e.id, type: e.type, value: e.value.substring(0,50)
                    })),
                    links: Array.from(document.querySelectorAll('a')).map(e=>({
                        text: e.innerText.trim(), href: e.href.substring(0,100)
                    })).filter(l=>l.text),
                    scripts: Array.from(document.querySelectorAll('script:not([src])')).map(s=>s.innerHTML.substring(0,500))
                };
            }""")
            (OUT/'acct_rec_forms.json').write_text(json.dumps(forms, indent=2))
            print(f"    Inputs: {len(forms['inputs'])}, Links: {len(forms['links'])}")
            for inp in forms['inputs']:
                print(f"      Input: {inp}")
            for lnk in forms['links'][:10]:
                print(f"      Link: {lnk}")

        if panel_frame:
            print(f"\n    Panel frame: {panel_frame.url}")
            text = await panel_frame.inner_text('body')
            print(f"    Panel text (first 500):\n{text[:500]}")
            html = await panel_frame.content()
            (OUT/'acct_panel.html').write_text(html)

        # Show all POST requests made
        print(f"\n[4] POST requests captured: {len(captured_reqs)}")
        for url, body in captured_reqs.items():
            print(f"  POST {url.split('goctl.com')[1][:80]}")
            print(f"       {body[:150]}")

        await br.close()

asyncio.run(run())
