import asyncio, os
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("[1] Logging in...")
        await login(pg)

        # Open ClientMaster, load Comet clients
        print("[2] Loading Comet clients...")
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

        # Use a KNOWN Comet account — Kirkland & Ellis (10016)
        # Try the xApi endpoint that's used internally
        print("\n[3] Trying xApi endpoints for client 3155 (Kirkland)...")
        for ep in [
            '/xApi/ClientMaster/GetClientProfile?ClientID=3155',
            '/xApi/Client/GetClient?ClientID=3155',
            '/xApi/profile/GetClientProfile?ClientID=3155',
            '/api/clientmaster/getprofile?ClientID=3155',
            '/api/clientmaster/getclient?ClientID=3155&TerminalID=22',
        ]:
            r = await pg.evaluate(f"""async () => {{
                const r = await fetch('{ep}');
                return {{status: r.status, body: (await r.text()).substring(0,300)}};
            }}""")
            if r['status'] < 404:
                print(f"    {ep}: {r['status']}")
                print(f"    {r['body'][:200]}")

        # Now navigate to the actual client profile page and read it rendered
        print("\n[4] Opening Kirkland client profile via oCM...")
        await pg.evaluate("() => { window.top.oCM(3155); }")
        await asyncio.sleep(5)

        # Find new frames
        for frame in pg.frames:
            if 'ClientMaster' in frame.url or 'clientmaster' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    if text.strip():
                        print(f"\n    Frame: {frame.url.split('goctl.com')[1][:70]}")
                        print(f"    Text:\n{text[:800]}")
                        html = await frame.content()
                        (OUT/f'client_profile_rendered.html').write_text(html)
                except: pass

        # Also check what the xApi/profile/GetProfile returns with client context
        print("\n[5] Trying GetProfile with client 3155...")
        r = await pg.evaluate("""async () => {
            const r = await fetch('/xApi/profile/GetProfile', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ClientID: 3155, TerminalID: 22})
            });
            return {status: r.status, body: (await r.text()).substring(0, 500)};
        }""")
        print(f"    Status: {r['status']}")
        print(f"    Body: {r['body'][:300]}")

        # Try the addresses endpoint we saw: Ladd(3155,'Kirkland')
        print("\n[6] Trying Addresses endpoint...")
        for ep in [
            '/Client/ClientMaster/Addresses/Addresses.aspx?ClientID=3155',
            '/Client/ClientMaster/ClientMasterBody.aspx?ClientID=3155&METHOD=GET&Section=Addresses',
            '/xApi/ClientMaster/GetAddresses?ClientID=3155',
            '/api/clientmaster/getaddresses?ClientID=3155',
        ]:
            r = await pg.evaluate(f"""async () => {{
                const r = await fetch('{ep}');
                return {{status: r.status, body: (await r.text()).substring(0,400)}};
            }}""")
            print(f"    {ep.split('?')[0].split('/')[-1]}: {r['status']}")
            if r['status'] < 400 and len(r['body'].strip()) > 50:
                print(f"    {r['body'][:200]}")

        await br.close()

asyncio.run(run())
