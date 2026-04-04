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

        # Get full report data with ReportFile paths
        print("\n[2] Getting full report list with file paths...")
        report_json = await pg.evaluate("""async () => {
            const r = await fetch('/api/reportlist/GetReports');
            return await r.text();
        }""")
        data = json.loads(report_json)
        (OUT/'report_list_full.json').write_text(report_json)

        # Find all reports with ReportFile
        def collect_reports(node, results=None):
            if results is None: results = []
            if isinstance(node, dict):
                if 'ReportFile' in node and node['ReportFile']:
                    # Extract text from HTML
                    text = re.sub(r'<[^>]+>', '', node.get('text',''))
                    results.append({'name': text.strip(), 'file': node['ReportFile'], 'id': node.get('ReportID')})
                for v in node.values():
                    collect_reports(v, results)
            elif isinstance(node, list):
                for item in node:
                    collect_reports(item, results)
            return results

        reports = collect_reports(data)
        print(f"    {len(reports)} reports with file paths found")
        # Find client-related ones
        for r in reports:
            if any(x in r['name'].lower() for x in ['client', 'address', 'active', 'account']):
                print(f"    {r['name']} → {r['file']}")

        # Open Standard Reports to establish context
        print("\n[3] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(5)

        std_frame = next((f for f in pg.frames if 'standardreport' in f.url.lower()), None)
        if not std_frame:
            print("Frame not found"); await br.close(); return

        # Navigate the subframe to Active Clients Report
        # Find the report file for Active Clients
        active_report = next((r for r in reports if 'active clients' in r['name'].lower()), None)
        addr_report = next((r for r in reports if 'client addresses' in r['name'].lower()), None)

        print(f"\n[4] Active Clients Report: {active_report}")
        print(f"    Client Addresses Report: {addr_report}")

        # Load the subframe and then navigate to the report
        sub_url = 'standardreports/standardreportssubframe'

        # Navigate the sr1_Frame to the subframe URL first
        await std_frame.evaluate(f"""() => {{
            document.getElementById('sr1_Frame').src = '{sub_url}';
        }}""")
        await asyncio.sleep(3)

        # Find the subframe
        sub_frame = next((f for f in pg.frames if 'standardreportssubframe' in f.url.lower()), None)
        print(f"\n[5] Subframe: {sub_frame.url if sub_frame else 'NOT FOUND'}")

        if sub_frame and active_report:
            # Navigate to the Active Clients report file
            report_file = active_report['file']
            print(f"    Loading report: {report_file}")

            before = set(captured_reqs.keys())
            await sub_frame.goto(f'https://www.goctl.com/reports/standardreports/{report_file}',
                                 wait_until='domcontentloaded')
            await asyncio.sleep(4)

            text = await sub_frame.inner_text('body')
            print(f"\n[6] Report page text:\n{text[:800]}")
            html = await sub_frame.content()
            (OUT/f'active_clients_rpt.html').write_text(html)

            # Find inputs/form
            inputs = await sub_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('input, select')).map(e => ({
                    name: e.name, id: e.id, type: e.type,
                    value: (e.value||'').substring(0,30)
                }))
            """)
            print(f"\n[7] Report form inputs:")
            for i in inputs:
                print(f"    {i}")

        await br.close()

asyncio.run(run())
