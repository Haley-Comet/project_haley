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
                captured_reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:300]}
            except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        print("\n[2] Opening ClientMaster frame...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(8)

        # List all frames
        print("\n[3] Frames loaded:")
        for frame in pg.frames:
            if 'goctl.com' in frame.url and 'Main/Home' not in frame.url:
                print(f"    {frame.url}")

        # Find client frame
        client_frame = None
        for frame in pg.frames:
            if 'client' in frame.url.lower() or 'Client' in frame.url:
                if 'Main' not in frame.url:
                    client_frame = frame
                    print(f"    → Using: {frame.url}")

        await pg.screenshot(path=str(SS/'client_master.png'), full_page=True)

        if client_frame:
            # Get page text and inputs
            text = await client_frame.inner_text('body')
            print(f"\n[4] Page text:\n{text[:600]}")

            html = await client_frame.content()
            (OUT/'client_master.html').write_text(html)

            clickables = await client_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('a, input[type=submit], input[type=button], button')).map(e => ({
                    tag: e.tagName,
                    text: e.innerText.trim() || e.value || '',
                    onclick: (e.getAttribute('onclick') || '').substring(0,150),
                    href: (e.href || '').substring(0,100)
                })).filter(e => e.text)
            """)
            print(f"\n[5] Clickable elements:")
            for c in clickables:
                print(f"    {c['tag']} '{c['text']}' onclick={c['onclick'][:80]} href={c['href'][:60]}")

            inputs = await client_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('input,select')).map(e => ({
                    name: e.name, id: e.id, type: e.type, value: (e.value||'').substring(0,30)
                }))
            """)
            print(f"\n[6] Inputs:")
            for i in inputs:
                print(f"    {i}")

            # Check for JS scripts loaded
            scripts = await client_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('script[src]'))
                    .map(s => s.src)
                    .filter(s => s.includes('goctl'))
            """)
            print(f"\n[7] Scripts loaded:")
            for s in scripts:
                print(f"    {s}")

        # New JSON APIs
        print(f"\n[8] JSON APIs captured:")
        for url, body in captured.items():
            if body.strip()[:1] in '[{' and '/api/' in url:
                path = url.split('goctl.com')[1].split('?')[0]
                if path not in ['/api/userbar/menu', '/api/profilecontrols/getemployeeprofile',
                                 '/api/dashboard/getReportList', '/api/dashboard/gettotals',
                                 '/api/dashboard/getcompanynews', '/api/dashboard/getindustrynews',
                                 '/api/dashboard/getkssnews']:
                    print(f"    {path}")
                    print(f"    {body[:200]}")

        await br.close()

asyncio.run(run())
