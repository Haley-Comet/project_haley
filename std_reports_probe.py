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
                captured[r.url] = b[:100000]
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

        # Open Standard Reports
        print("\n[2] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(6)

        print("\n[3] All frames:")
        for frame in pg.frames:
            if 'goctl.com' in frame.url and 'Main/Home' not in frame.url:
                print(f"    {frame.url}")

        # Find and read the standard reports frame
        for frame in pg.frames:
            if 'standard' in frame.url.lower() or 'report' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    if text.strip():
                        print(f"\n[4] Frame {frame.url.split('goctl.com')[1][:60]}:")
                        print(f"    {text[:800]}")
                        html = await frame.content()
                        (OUT/f'std_rep_{frame.url.split("/")[-1].split("?")[0]}.html').write_text(html)

                        # Find all links/buttons
                        clickables = await frame.evaluate("""() =>
                            Array.from(document.querySelectorAll('a, input[type=submit], button, select')).map(e => ({
                                tag: e.tagName,
                                text: (e.innerText||e.value||'').trim().substring(0,50),
                                href: (e.href||'').substring(0,80),
                                onclick: (e.getAttribute('onclick')||'').substring(0,100)
                            })).filter(e => e.text)
                        """)
                        print(f"\n    Clickable elements:")
                        for c in clickables[:20]:
                            print(f"    {c['tag']} '{c['text']}' {c['href'] or c['onclick']}")
                except: pass

        # Probe standard report APIs
        print("\n[5] Probing standard report APIs for client list...")
        for ep in [
            '/api/reports/getclientlist?TerminalID=22&Status=A',
            '/api/standardreports/clientlist?TerminalID=22',
            '/Reports/StandardReports/ClientList.aspx?TerminalID=22',
            '/reports/standardreports/getreports',
            '/api/reports/getreportlist',
            '/xApi/Reports/GetClientMasterReport?TerminalID=22',
        ]:
            r = await pg.evaluate(f"""async () => {{
                const r = await fetch('{ep}');
                const t = await r.text();
                return {{status: r.status, ct: r.headers.get('content-type'), body: t.substring(0,200)}};
            }}""")
            if r['status'] < 404:
                print(f"    {ep.split('?')[0].split('/')[-1]}: {r['status']} {r['ct']}")
                if r['body'].strip()[:1] in '[{':
                    print(f"    JSON! → {r['body'][:300]}")
                else:
                    print(f"    → {r['body'][:100]}")

        # Check what APIs fired while loading StandardRep
        print(f"\n[6] New JSON APIs from StandardRep load:")
        for url, body in captured.items():
            if body.strip()[:1] in '[{' and '/api/' in url and 'dashboard' not in url:
                print(f"    {url.split('goctl.com')[1][:80]}")
                print(f"    {body[:200]}")

        await br.close()

asyncio.run(run())
