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
    js_files = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await br.new_context(viewport={'width':1440,'height':900})
        pg = await ctx.new_page()
        pg.set_default_timeout(30000)

        async def on_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                url_lower = r.url.lower()
                if any(x in url_lower for x in ['toolbar', 'frame', 'menu', 'userbar']):
                    js_files[r.url] = b
            except: pass

        pg.on('response', on_resp)
        await login(pg)
        print(f"Logged in. Captured {len(js_files)} JS files.")

        for url, content in js_files.items():
            short = url.split('?')[0].split('/')[-1]
            # Search for ClientMaster references
            if 'client' in content.lower() or 'ClientMaster' in content:
                matches = re.findall(r'.{0,80}[Cc]lientMaster.{0,80}', content)
                if matches:
                    print(f"\n=== {short} — ClientMaster refs ===")
                    for m in matches[:10]:
                        print(f"  {m.strip()}")

            # Search for OpenWindow calls with paths
            ow_matches = re.findall(r'OpenWindow\([^)]{10,200}\)', content)
            if ow_matches:
                print(f"\n=== {short} — OpenWindow calls ===")
                for m in ow_matches[:15]:
                    print(f"  {m[:150]}")

        # Also try direct API calls that might give client data
        print("\n=== Trying direct API calls for client 10016 ===")
        captured = {}
        async def on_resp2(r):
            if '/api/' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured[r.url] = json.loads(b)
            except: pass
        pg.on('response', on_resp2)

        api_candidates = [
            '/api/clients/GetClient?clientID=10016',
            '/api/clients/getclient?AccountNo=10016',
            '/api/clientmaster/GetClient?id=10016',
            '/api/accounting/GetClientDetails?id=10016',
            '/api/controls/GetClients?search=kirkland',
        ]
        for path in api_candidates:
            result = await pg.evaluate(f"""async () => {{
                const r = await fetch('{path}');
                return {{status: r.status, body: (await r.text()).slice(0, 300)}};
            }}""")
            print(f"  {path} → {result['status']}: {result['body'][:150]}")

        await br.close()

asyncio.run(run())
