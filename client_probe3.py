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

        popup_pages = []
        popup_captured = {}

        async def on_popup(popup):
            popup_pages.append(popup)
            print(f"  POPUP: {popup.url}")
            async def on_resp(r):
                if 'goctl.com' not in r.url: return
                try:
                    b = await r.text()
                    if b.strip()[:1] in '[{':
                        popup_captured[r.url] = json.loads(b)
                    else:
                        popup_captured[r.url] = b[:200]
                except: pass
            popup.on('response', on_resp)

        ctx.on('page', on_popup)
        await login(pg)
        print("Logged in.")

        # First — find what far= prefix is in frame.js
        far = await pg.evaluate("() => typeof far !== 'undefined' ? far : window.far || 'unknown'")
        print(f"far = {far}")

        # Step 1: try account number directly as ClientID
        # Also try to find the search/lookup API to get ClientID from AccountNo
        print("\n=== Step 1: Search API to find ClientID from AccountNo ===")
        search_apis = [
            '/api/clientmaster/search?q=10016',
            '/api/clientmaster/search?accountNo=10016',
            '/api/clients/search?term=kirkland',
            '/api/clients/search?q=10016',
            '/api/controls/GetClients?accountNo=10016',
            '/api/controls/getclientbyaccount?accountNo=10016',
            '/api/clientmaster/GetClientByAccountNo?accountNo=10016',
        ]
        for path in search_apis:
            result = await pg.evaluate(f"""async () => {{
                const r = await fetch('{path}');
                const t = await r.text();
                return {{status: r.status, body: t.slice(0, 200)}};
            }}""")
            if result['status'] == 200 and result['body'].strip()[:1] in '[{{':
                print(f"  HIT: {path} → {result['body'][:300]}")
            else:
                print(f"  {result['status']}: {path}")

        # Step 2: Open the ClientMasterFrame with account number as ClientID (might work)
        print("\n=== Step 2: Open ClientMasterFrame directly ===")
        for client_id in [10016, 1, 100]:
            popup_pages.clear()
            popup_captured.clear()

            url = f"https://www.goctl.com/Main/Client/ClientMaster/ClientMasterFrame.aspx?ClientID={client_id}&TimezoneAbbrev=UTC"
            print(f"\nTrying ClientID={client_id}: {url}")

            await pg.evaluate(f"() => window.open('{url}', 'CMTest{client_id}', 'width=1200,height=800')")
            await asyncio.sleep(6)

            if popup_pages:
                pp = popup_pages[-1]
                final_url = pp.url
                print(f"  Final URL: {final_url}")
                try:
                    await pp.wait_for_load_state('load', timeout=10000)
                    title = await pp.title()
                    print(f"  Title: {title}")
                    api = [u for u in popup_captured if '/api/' in u]
                    print(f"  API calls ({len(api)}): {api[:5]}")
                    for u in api[:3]:
                        v = popup_captured[u]
                        print(f"    {u}")
                        print(f"    {json.dumps(v)[:400] if isinstance(v,(dict,list)) else v[:200]}")
                    if not api:
                        html = await pp.content()
                        # Look for any account/client data in HTML
                        acct_matches = re.findall(r'(ClientID|AccountNo|clientId|accountNo)["\s:=]+(["\d\w]+)', html)
                        print(f"  ID patterns in HTML: {acct_matches[:5]}")
                        print(f"  HTML snippet: {html[1000:2000]}")
                except Exception as e:
                    print(f"  Error: {e}")
                try: await pp.close()
                except: pass
            else:
                print("  No popup opened")

        await br.close()

asyncio.run(run())
