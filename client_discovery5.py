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

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:100000]
            except: pass
        pg.on('response', cap_resp)

        print("[1] Logging in...")
        await login(pg)

        print("\n[2] Opening ClientMaster + loading Comet clients...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(6)

        panel = next((f for f in pg.frames
                      if 'Panel.aspx' in f.url and 'Client' in f.url and 'Top' not in f.url), None)
        if panel:
            await panel.evaluate("""() => {
                document.getElementById('TerminalID').value = '22';
                const statusSel = document.getElementById('Status');
                if (statusSel) statusSel.value = 'A';
                document.getElementById('MaxRecords').value = '9999';
                document.loadtoolbarform.submit();
            }""")
            await asyncio.sleep(8)

        # Now find the toolbar frame with client list and click first client
        toolbar = next((f for f in pg.frames if 'ClientToolbar.aspx' in f.url
                        and 'METHOD' not in f.url), None)

        if toolbar:
            text = await toolbar.inner_text('body')
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            print(f"\n[3] Client list ({len(lines)} entries):")
            for l in lines[:10]:
                print(f"    {l}")
            print(f"    ... and {len(lines)-10} more")

            # Get the HTML to find client IDs
            html = await toolbar.content()
            (OUT/'client_toolbar_loaded.html').write_text(html)

            # Extract client links with IDs
            clients = await toolbar.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[ClientName], span[clientid], a[clientid]'))
                    .map(e => ({
                        name: e.getAttribute('ClientName') || e.getAttribute('clientname') || e.innerText.trim(),
                        id: e.getAttribute('clientid') || e.getAttribute('ClientID') || '',
                        onclick: (e.getAttribute('onclick')||'').substring(0,100)
                    })).filter(e => e.name);
            }""")
            print(f"\n[4] Client entries with IDs: {len(clients)}")
            for c in clients[:10]:
                print(f"    {c}")

            # If no IDs found, look at all links
            if not clients:
                all_links = await toolbar.evaluate("""() =>
                    Array.from(document.querySelectorAll('a, span')).map(e => ({
                        text: e.innerText.trim().substring(0,40),
                        attrs: Array.from(e.attributes).map(a => a.name+'='+a.value.substring(0,30)).join(' ')
                    })).filter(e => e.text && e.text.length > 2).slice(0,15)
                """)
                print(f"\n    First 15 links/spans:")
                for l in all_links:
                    print(f"    '{l['text']}' attrs: {l['attrs']}")

        # Try hitting the API endpoint we found earlier directly
        print(f"\n[5] Hitting client API endpoints...")
        endpoints = [
            '/api/clients/getclients?TerminalID=22&Status=A',
            '/api/client/getclients?TerminalID=22',
            '/api/controls/getclients?TerminalID=22',
            '/api/clientmaster/getclients?TerminalID=22',
            '/xApi/client/GetClients?TerminalID=22',
            '/xApi/ClientMaster/GetClients?TerminalID=22&Status=A',
        ]
        for ep in endpoints:
            result = await pg.evaluate(f"""async () => {{
                const r = await fetch('{ep}');
                return {{status: r.status, body: (await r.text()).substring(0, 200)}};
            }}""")
            if result['status'] < 400 and result['body'].strip()[:1] in '[{{':
                print(f"    ✓ {ep} → {result['status']}")
                print(f"      {result['body'][:200]}")

        # Save the main client body HTML
        main_body_url = next((url for url in captured if 'MainClientBody' in url), None)
        if main_body_url:
            body = captured[main_body_url]
            (OUT/'main_client_body_full.html').write_text(body)
            print(f"\n[6] MainClientBody saved: {len(body)} chars")
            # Find client IDs in it
            import re
            ids = re.findall(r'ClientID[=\s]+(\d+)', body)
            names = re.findall(r'ClientName[="\s]+([^"&\n]+)', body)
            print(f"    Client IDs found: {ids[:10]}")
            print(f"    Client Names found: {names[:10]}")

        await br.close()

asyncio.run(run())
