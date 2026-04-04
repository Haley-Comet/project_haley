import asyncio, os, json, re, requests
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
        pg.set_default_timeout(60000)

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
                document.getElementById('Status').value = 'A';
                document.getElementById('MaxRecords').value = '9999';
                document.loadtoolbarform.submit();
            }""")
            await asyncio.sleep(8)

        # Parse all client IDs + names from toolbar
        toolbar = next((f for f in pg.frames
                        if 'ClientToolbar.aspx' in f.url and 'METHOD' not in f.url), None)
        if not toolbar:
            print("Toolbar not found"); await br.close(); return

        clients = await toolbar.evaluate("""() => {
            const results = [];
            // Find all client links
            document.querySelectorAll('a.clientlink, a[onclick*="WM_toggle"]').forEach(a => {
                const onclick = a.getAttribute('onclick') || '';
                const match = onclick.match(/WM_toggle\('X(\d+)'\)/);
                if (match) {
                    const id = match[1];
                    const name = a.innerText.trim();
                    results.push({id, name});
                }
            });
            return results;
        }""")
        print(f"\n[3] Extracted {len(clients)} clients with IDs")
        for c in clients[:5]:
            print(f"    {c}")

        if not clients:
            # Fallback: parse from saved HTML
            html = await toolbar.content()
            (OUT/'toolbar_full.html').write_text(html)
            matches = re.findall(r"WM_toggle\('X(\d+)'\)[^>]*>([^<]+)<", html)
            clients = [{'id': m[0], 'name': m[1].strip()} for m in matches]
            print(f"    Fallback regex found {len(clients)} clients")
            for c in clients[:5]:
                print(f"    {c}")

        # Now intercept what oCM() calls for a real client
        print(f"\n[4] Opening client profile for first client ({clients[0] if clients else 'N/A'})...")
        if clients:
            sample_id = clients[0]['id']
            before = set(captured.keys())
            await pg.evaluate(f"() => {{ window.top.oCM({sample_id}); }}")
            await asyncio.sleep(5)
            await pg.screenshot(path=str(SS/'client_profile.png'), full_page=True)

            new = {k: v for k, v in captured.items() if k not in before and 'goctl.com' in k}
            print(f"    New requests: {len(new)}")
            for url, body in new.items():
                path = url.split('goctl.com')[1][:80]
                print(f"    {path}")
                if body.strip()[:1] in '[{':
                    print(f"    JSON: {body[:300]}")
                else:
                    print(f"    HTML: {body[:300]}")

        # Try xApi endpoints for bulk client data
        print(f"\n[5] Probing bulk client APIs...")
        apis = [
            '/xApi/Client/GetClientList?TerminalID=22&Status=A',
            '/xApi/ClientMaster/GetClientList?TerminalID=22',
            '/api/clientmaster/getclientlist?TerminalID=22',
            '/api/client/list?TerminalID=22&Status=A',
            f'/Client/ClientMaster/ClientMasterBody.aspx?ClientID={clients[0]["id"] if clients else "3779"}&METHOD=GET',
        ]
        for ep in apis:
            try:
                result = await pg.evaluate(f"""async () => {{
                    const r = await fetch('{ep}');
                    const t = await r.text();
                    return {{status: r.status, body: t.substring(0,300)}};
                }}""")
                print(f"    {ep.split('?')[0]}: {result['status']}")
                if result['status'] < 400:
                    print(f"    → {result['body'][:150]}")
            except: pass

        # Try loading individual client profile via known endpoint pattern
        if clients:
            sample_id = clients[0]['id']
            print(f"\n[6] Loading client {sample_id} profile directly...")
            result = await pg.evaluate(f"""async () => {{
                const r = await fetch('/Client/ClientMaster/ClientMasterBody.aspx?ClientID={sample_id}&METHOD=GET');
                return {{status: r.status, body: (await r.text()).substring(0,1000)}};
            }}""")
            print(f"    Status: {result['status']}")
            print(f"    Body: {result['body'][:500]}")
            (OUT/f'client_profile_{sample_id}.html').write_text(result['body'])

        (OUT/'clients_list.json').write_text(json.dumps(clients, indent=2))
        print(f"\n    Saved {len(clients)} client IDs to clients_list.json")
        await br.close()

asyncio.run(run())
