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
        pg.set_default_timeout(60000)

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:500000]
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

        # Read the render JS to find how reports are loaded
        print("\n[2] Reading StandardReports_render.js...")
        render_js = await pg.evaluate("""async () => {
            const r = await fetch('/Areas/Reports/Scripts/StandardReports_render.js');
            return await r.text();
        }""")
        (OUT/'std_render.js').write_text(render_js)
        print(f"    {len(render_js)} chars")
        for line in render_js.split('\n'):
            s = line.strip()
            if s and any(x in s.lower() for x in ['url', 'api/', 'ajax', 'fetch', 'post', 'datasource', 'active', 'client', 'report']):
                print(f"    {s[:160]}")

        # Open Standard Reports
        print("\n[3] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(6)

        std_frame = next((f for f in pg.frames if 'standardreport' in f.url.lower()), None)
        if not std_frame:
            print("Frame not found"); await br.close(); return

        # Read config JS too
        print("\n[4] Reading StandardReports_config.js...")
        config_js = await pg.evaluate("""async () => {
            const r = await fetch('/Areas/Reports/Scripts/StandardReports_config.js');
            return await r.text();
        }""")
        (OUT/'std_config.js').write_text(config_js)
        for line in config_js.split('\n'):
            s = line.strip()
            if s and any(x in s.lower() for x in ['url', 'api/', 'active', 'client', 'report', 'terminal', 'ajax']):
                print(f"    {s[:160]}")

        # Get report list structure to find Active Clients report linkID
        report_list = await pg.evaluate("""async () => {
            const r = await fetch('/api/reportlist/GetReports');
            return await r.text();
        }""")
        data = json.loads(report_list)

        # Find Active Clients Report
        def find_report(node, target):
            if isinstance(node, dict):
                text = node.get('text', '') or ''
                if target.lower() in text.lower():
                    return node
                for v in node.values():
                    found = find_report(v, target)
                    if found: return found
            elif isinstance(node, list):
                for item in node:
                    found = find_report(item, target)
                    if found: return found
            return None

        active_report = find_report(data, 'Active Clients Report')
        new_updated = find_report(data, 'New/Updated Clients')
        client_addresses = find_report(data, 'Client Addresses')

        print(f"\n[5] Active Clients Report: {json.dumps(active_report)[:300] if active_report else 'NOT FOUND'}")
        print(f"\n    New/Updated Clients: {json.dumps(new_updated)[:300] if new_updated else 'NOT FOUND'}")
        print(f"\n    Client Addresses: {json.dumps(client_addresses)[:300] if client_addresses else 'NOT FOUND'}")

        # Try loading Active Clients report by clicking it in the UI
        print("\n[6] Clicking Active Clients Report in UI...")
        before = set(captured.keys())
        before_reqs = set(captured_reqs.keys())

        # Try calling the report load function directly
        result = await std_frame.evaluate("""() => {
            // Find all links
            const all = Array.from(document.querySelectorAll('a, li, div[onclick]'));
            const target = all.find(e => (e.innerText||'').includes('Active Clients'));
            if (target) { target.click(); return 'clicked: ' + target.innerText.substring(0,50); }

            // Try calling directly if there's a function
            const fns = Object.keys(window).filter(k => typeof window[k] === 'function' &&
                (k.toLowerCase().includes('report') || k.toLowerCase().includes('load')));
            return 'not found. Functions: ' + fns.slice(0,10).join(', ');
        }""")
        print(f"    {result}")
        await asyncio.sleep(6)
        await pg.screenshot(path=str(SS/'active_clients_rpt.png'), full_page=True)

        # New responses
        new_resp = {k:v for k,v in captured.items() if k not in before}
        new_reqs = {k:v for k,v in captured_reqs.items() if k not in before_reqs}

        print(f"\n[7] New requests: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"         {data['body'][:150]}")

        print(f"\n[8] New JSON responses:")
        for url, body in new_resp.items():
            if body.strip()[:1] in '[{':
                print(f"    {url.split('goctl.com')[1][:80]}")
                print(f"    {body[:300]}")

        await br.close()

asyncio.run(run())
