import asyncio, os, json, re
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
OUT  = Path('/opt/xcelerator/output')
SS   = Path('/opt/xcelerator/screenshots')

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
                captured[r.url] = b[:50000]
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

        print("[2] Opening ClientMaster + Comet clients...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(6)

        panel = next((f for f in pg.frames
                      if 'Panel.aspx' in f.url and 'Client' in f.url and 'Top' not in f.url), None)
        await panel.evaluate("""() => {
            document.getElementById('TerminalID').value = '22';
            document.getElementById('Status').value = 'A';
            document.getElementById('MaxRecords').value = '9999';
            document.loadtoolbarform.submit();
        }""")
        await asyncio.sleep(6)

        toolbar = next((f for f in pg.frames
                        if 'ClientToolbar.aspx' in f.url and 'METHOD' not in f.url), None)

        # Click on Kirkland & Ellis in the toolbar (client 3155)
        print("\n[3] Clicking Kirkland & Ellis in toolbar...")
        before_req = set(captured_reqs.keys())
        before_resp = set(captured.keys())

        await toolbar.evaluate("""() => {
            // Find and click the Kirkland link
            const links = Array.from(document.querySelectorAll('a.clientlink'));
            const kl = links.find(l => l.innerText.includes('Kirkland'));
            if (kl) { kl.click(); return 'clicked'; }
            return 'not found';
        }""")
        await asyncio.sleep(5)
        await pg.screenshot(path=str(SS/'client_kirkland_clicked.png'), full_page=True)

        # New requests/responses
        new_reqs = {k:v for k,v in captured_reqs.items() if k not in before_req}
        new_resp = {k:v for k,v in captured.items() if k not in before_resp}

        print(f"\n[4] New requests after clicking client: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"         {data['body'][:150]}")

        print(f"\n[5] New responses: {len(new_resp)}")
        for url, body in new_resp.items():
            path = url.split('goctl.com')[1][:80]
            print(f"\n    {path}")
            if body.strip()[:1] in '[{':
                print(f"    JSON: {body[:400]}")
            else:
                # Parse text
                clean = re.sub(r'<[^>]+>', ' ', body)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if len(clean) > 20:
                    print(f"    TEXT: {clean[:400]}")
            (OUT/f'client_click_{path.replace("/","_")}.html').write_text(body)

        # Also check rendered frames
        print(f"\n[6] Frame text after click:")
        for frame in pg.frames:
            if 'ClientMaster' in frame.url or 'client' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    if len(text.strip()) > 100 and 'ClientToolbar' not in frame.url:
                        print(f"\n    {frame.url.split('goctl.com')[1][:70]}")
                        print(f"    {text[:600]}")
                except: pass

        await br.close()

asyncio.run(run())
