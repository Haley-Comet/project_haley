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

        print("\n[2] Opening ClientMaster...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(6)

        # Find Panel.aspx and set Comet + Active then click Load
        panel_frame = next((f for f in pg.frames if 'Panel.aspx' in f.url and 'Client' in f.url), None)
        if not panel_frame:
            print("Panel not found"); await br.close(); return

        print(f"    Panel found: {panel_frame.url}")

        # Dump all inputs in panel
        inputs = await panel_frame.evaluate("""() =>
            Array.from(document.querySelectorAll('input, select, a')).map(e => ({
                tag: e.tagName, name: e.name, id: e.id, type: e.type,
                value: (e.value||'').substring(0,30),
                text: (e.innerText||e.value||'').trim().substring(0,40),
                onclick: (e.getAttribute('onclick')||'').substring(0,100)
            })).filter(e => e.text || e.name)
        """)
        print(f"\n[3] Panel inputs/links:")
        for i in inputs:
            print(f"    {i}")

        # Set Comet terminal and Active status, max records, then click Load
        print("\n[4] Setting Comet/Active and clicking Load...")
        before = set(captured_reqs.keys())

        result = await panel_frame.evaluate("""() => {
            try {
                // Set Del Center to Comet (terminal 22)
                const termSel = document.querySelector('select[name="TerminalID"]') ||
                                 document.querySelector('select[name="Terminal"]');
                if (termSel) {
                    for (let opt of termSel.options) {
                        opt.selected = opt.text.trim() === 'Comet';
                    }
                }

                // Set Status to Active
                const statusSel = document.querySelector('select[name="Status"]') ||
                                   document.querySelector('select[name="StatusID"]');
                if (statusSel) {
                    for (let opt of statusSel.options) {
                        opt.selected = opt.text.trim() === 'Active';
                    }
                }

                // Set max records high
                const maxRec = document.querySelector('input[name="MaxRecords"]') ||
                                document.querySelector('input[name="Max"]');
                if (maxRec) maxRec.value = '9999';

                // Find and click Load button
                const all = Array.from(document.querySelectorAll('a, input[type=submit], input[type=button], button'));
                const loadBtn = all.find(e =>
                    (e.innerText||e.value||'').toLowerCase().includes('load') ||
                    (e.getAttribute('onclick')||'').toLowerCase().includes('load')
                );
                if (loadBtn) { loadBtn.click(); return 'clicked: ' + (loadBtn.innerText||loadBtn.value||loadBtn.getAttribute('onclick')); }

                // Try submitting the form directly
                const form = document.querySelector('form');
                if (form) { form.submit(); return 'form submitted'; }

                return 'no load button found — elements: ' + all.map(e=>e.innerText||e.value).join(', ');
            } catch(e) { return 'error: ' + e; }
        }""")
        print(f"    Result: {result}")
        await asyncio.sleep(8)
        await pg.screenshot(path=str(SS/'client_list.png'), full_page=True)

        # Check new requests
        new_reqs = {k: v for k, v in captured_reqs.items() if k not in before}
        print(f"\n[5] New requests after Load: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"         {data['body'][:200]}")

        # Read MainClientBody frame
        print(f"\n[6] All frames after Load:")
        for frame in pg.frames:
            if 'Client' in frame.url and 'Main' not in frame.url:
                try:
                    text = await frame.inner_text('body')
                    fname = frame.url.split('/')[-1].split('?')[0]
                    if text.strip():
                        print(f"\n    {frame.url.split('goctl.com')[1][:70]}")
                        print(f"    {text[:600]}")
                    html = await frame.content()
                    (OUT/f'client_body_{fname}.html').write_text(html)
                except: pass

        await br.close()

asyncio.run(run())
