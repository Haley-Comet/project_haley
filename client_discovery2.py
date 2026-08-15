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
                captured[r.url] = b[:10000]
            except: pass

        async def cap_req(r):
            if 'goctl.com' not in r.url: return
            try:
                captured_reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:500]}
            except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        # Read Toolbar.js first
        print("\n[2] Reading Toolbar.js...")
        toolbar_js = await pg.evaluate("""async () => {
            const r = await fetch('/Client/ClientFrame/Toolbar.js');
            return await r.text();
        }""")
        (OUT/'client_toolbar.js').write_text(toolbar_js)
        print(f"    {len(toolbar_js)} chars")
        for line in toolbar_js.split('\n'):
            s = line.strip()
            if s and any(x in s.lower() for x in ['url', 'api/', 'ajax', 'fetch', 'post', 'get', 'client', 'terminal', 'export']):
                print(f"    {s[:160]}")

        print("\n[3] Opening ClientMaster...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(8)

        # Read all client-related frames
        for frame in pg.frames:
            if 'Client' in frame.url and 'Main' not in frame.url:
                try:
                    text = await frame.inner_text('body')
                    if text.strip():
                        fname = frame.url.split('/')[-1].split('?')[0]
                        print(f"\n[4] Frame {fname}:")
                        print(f"    {text[:400]}")

                    # Get all scripts in this frame
                    scripts = await frame.evaluate("""() =>
                        Array.from(document.querySelectorAll('script[src]'))
                            .map(s => s.src).filter(s => s.includes('goctl'))
                    """)
                    for s in scripts:
                        print(f"    script: {s.split('goctl.com')[1].split('?')[0]}")

                    # Save HTML
                    html = await frame.content()
                    (OUT/f'client_{fname}.html').write_text(html)
                except: pass

        # Submit the client list form
        print("\n[5] Submitting client list form (Comet terminal 22)...")
        toolbar_frame = next((f for f in pg.frames if 'ClientToolbar' in f.url), None)
        top_frame = next((f for f in pg.frames if 'Top-Panel' in f.url), None)

        if toolbar_frame:
            print(f"    Toolbar frame: {toolbar_frame.url}")
            # Set terminal to Comet and submit
            result = await toolbar_frame.evaluate("""() => {
                try {
                    // Set terminal
                    const termSel = document.querySelector('select[name="TerminalID"]') ||
                                    document.querySelector('#TerminalID');
                    if (termSel) {
                        termSel.value = '22';
                        console.log('terminal set to 22');
                    }
                    // Submit the form
                    const form = document.getElementById('updateBODY') ||
                                 document.querySelector('form');
                    if (form) { form.submit(); return 'submitted'; }
                    return 'form not found';
                } catch(e) { return 'error: ' + e; }
            }""")
            print(f"    Result: {result}")
            await asyncio.sleep(6)

        # Check all new requests/responses
        print(f"\n[6] All POST/GET requests to client endpoints:")
        for url, data in captured_reqs.items():
            if any(x in url.lower() for x in ['client', 'acct', 'account']):
                print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
                if data['body']:
                    print(f"         {data['body'][:200]}")

        print(f"\n[7] JSON API responses:")
        for url, body in captured.items():
            if body.strip()[:1] in '[{' and '/api/' in url:
                path = url.split('goctl.com')[1].split('?')[0]
                if 'dashboard' not in path and 'userbar' not in path:
                    print(f"    {path}")
                    print(f"    {body[:300]}")

        # Check frame content after submit
        print(f"\n[8] Frame content after submit:")
        for frame in pg.frames:
            if 'Client' in frame.url and 'Main' not in frame.url:
                try:
                    text = await frame.inner_text('body')
                    if len(text.strip()) > 50:
                        print(f"\n    {frame.url.split('goctl.com')[1][:60]}")
                        print(f"    {text[:500]}")
                except: pass

        await br.close()

asyncio.run(run())
