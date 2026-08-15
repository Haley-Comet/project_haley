import asyncio, os, json, re, requests
from pathlib import Path
from datetime import datetime

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL']
KEY  = os.environ['SUPABASE_KEY']
OUT  = Path('/opt/xcelerator/output')
SS   = Path('/opt/xcelerator/screenshots')
HDRS = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates,return=minimal'}

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
                captured_reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:300]}
            except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        print("[2] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(5)

        std_frame = next((f for f in pg.frames if 'standardreport' in f.url.lower() and 'subframe' not in f.url.lower()), None)
        sub_frame = next((f for f in pg.frames if 'standardreportssubframe' in f.url.lower()), None)

        print(f"    std: {std_frame.url if std_frame else 'N/A'}")
        print(f"    sub: {sub_frame.url if sub_frame else 'N/A'}")

        # Use std_frame to trigger report load via buildReport pattern
        print("\n[3] Triggering Active Clients Report via parent frame function...")
        before = set(captured_reqs.keys())

        # The config JS shows: frameDoc_reportDoc.Form1.submit()
        # Reports load into sr1_Frame > reportFrame
        # Try setting the iframe src directly to the report
        result = await std_frame.evaluate("""() => {
            try {
                const sr1 = document.getElementById('sr1_Frame');
                if (!sr1) return 'sr1_Frame not found';

                // Navigate sr1_Frame to the report
                const subDoc = sr1.contentDocument || sr1.contentWindow.document;
                const reportFrame = subDoc.getElementById('reportFrame');
                if (reportFrame) {
                    reportFrame.src = 'ActiveClientsReport.aspx';
                    return 'set reportFrame src';
                }

                // Try calling buildReport in subframe context
                const subWin = sr1.contentWindow;
                if (subWin && typeof subWin.buildReport === 'function') {
                    subWin.buildReport(3); // ReportID 3
                    return 'called buildReport(3)';
                }

                // Find report tree and select Active Clients
                const tv = subWin.$('#reportTree').data('kendoTreeView');
                if (tv) {
                    const allNodes = tv.element.find('li');
                    const target = Array.from(allNodes).find(n => n.innerText.trim() === 'Active Clients Report');
                    if (target) {
                        tv.select($(target));
                        return 'selected via kendo: ' + target.innerText;
                    }
                }

                return 'subWin functions: ' + Object.keys(subWin).filter(k => typeof subWin[k] === 'function').slice(0,10).join(', ');
            } catch(e) { return 'error: ' + e; }
        }""")
        print(f"    Result: {result}")
        await asyncio.sleep(5)
        await pg.screenshot(path=str(SS/'active_rpt3.png'), full_page=True)

        new_reqs = {k:v for k,v in captured_reqs.items() if k not in before}
        print(f"\n    New requests: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"         {data['body'][:100]}")

        # Check for new frames
        print(f"\n[4] All frames:")
        for frame in pg.frames:
            if 'goctl.com' in frame.url:
                print(f"    {frame.url}")

        # Try loading report via subframe navigate
        print(f"\n[5] Directly navigating reportFrame to ActiveClientsReport.aspx...")
        before2 = set(captured_reqs.keys())

        if sub_frame:
            # Check what's inside subframe
            sub_html = await sub_frame.content()
            (OUT/'sub_frame_full.html').write_text(sub_html)

            # Find reportFrame inside subframe
            report_frame_src = await sub_frame.evaluate("""() => {
                const rf = document.getElementById('reportFrame');
                if (rf) return 'found: ' + rf.src;
                const frames = document.querySelectorAll('iframe, frame');
                return 'frames: ' + Array.from(frames).map(f => f.id + '=' + f.src).join(', ');
            }""")
            print(f"    reportFrame: {report_frame_src}")

            # Navigate reportFrame to the report
            result2 = await sub_frame.evaluate("""() => {
                const rf = document.getElementById('reportFrame');
                if (rf) {
                    rf.src = 'ActiveClientsReport.aspx';
                    return 'navigated';
                }
                return 'no reportFrame';
            }""")
            print(f"    Navigate result: {result2}")
            await asyncio.sleep(6)

        new_reqs2 = {k:v for k,v in captured_reqs.items() if k not in before2}
        print(f"\n    New requests after navigate: {len(new_reqs2)}")
        for url, data in new_reqs2.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")

        # Check report frame now
        report_frame = next((f for f in pg.frames if 'ActiveClients' in f.url or 'activeClients' in f.url.lower()), None)
        if report_frame:
            text = await report_frame.inner_text('body')
            print(f"\n[6] Report frame text:\n{text[:600]}")
            html = await report_frame.content()
            (OUT/'active_clients_loaded.html').write_text(html)
        else:
            # Check all frames for report content
            for frame in pg.frames:
                if 'goctl.com' in frame.url and frame.url != 'https://www.goctl.com/Main/home':
                    try:
                        text = await frame.inner_text('body')
                        if 'Terminal' in text or 'Delivery Center' in text or 'Active' in text:
                            if len(text) > 100:
                                print(f"\n[6] Possible report frame: {frame.url.split('goctl.com')[1][:60]}")
                                print(f"    {text[:400]}")
                    except: pass

        await br.close()

asyncio.run(run())
