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
        await asyncio.sleep(8)

        print("\n[3] All Client frames:")
        for frame in pg.frames:
            if 'Client' in frame.url and 'Main/Home' not in frame.url:
                print(f"    {frame.url}")

        # Target Panel.aspx specifically (not Top-Panel)
        panel_frame = next((f for f in pg.frames
                           if f.url.endswith('Panel.aspx') and 'Client' in f.url
                           and 'Top' not in f.url), None)

        if not panel_frame:
            # Try any panel
            panel_frame = next((f for f in pg.frames
                               if 'Panel.aspx' in f.url and 'Client' in f.url), None)

        print(f"\n[4] Using panel: {panel_frame.url if panel_frame else 'NOT FOUND'}")

        if panel_frame:
            # Dump everything in this frame
            html = await panel_frame.content()
            (OUT/'client_panel.html').write_text(html)

            inputs = await panel_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('input, select, a, button')).map(e => ({
                    tag: e.tagName, name: e.name, id: e.id, type: e.type,
                    value: (e.value||'').substring(0,30),
                    text: (e.innerText||e.value||'').trim().substring(0,50),
                    onclick: (e.getAttribute('onclick')||'').substring(0,120)
                }))
            """)
            print(f"\n    All elements:")
            for i in inputs:
                if i['text'] or i['name']:
                    print(f"    {i}")

            # Set Comet, Active, max records, click Load
            print("\n[5] Setting filters and loading...")
            before = set(captured_reqs.keys())

            result = await panel_frame.evaluate("""() => {
                try {
                    // Terminal/Del Center
                    const allSels = Array.from(document.querySelectorAll('select'));
                    console.log('Selects:', allSels.map(s => s.name + '=' + s.value));

                    allSels.forEach(sel => {
                        if (sel.name === 'TerminalID' || sel.name === 'Terminal' ||
                            sel.id === 'TerminalID') {
                            for (let opt of sel.options) {
                                opt.selected = opt.text.trim() === 'Comet' || opt.value === '22';
                            }
                        }
                        if (sel.name === 'Status' || sel.name === 'StatusID') {
                            for (let opt of sel.options) {
                                opt.selected = opt.text.trim() === 'Active';
                            }
                        }
                    });

                    // Max records
                    const allInputs = Array.from(document.querySelectorAll('input'));
                    allInputs.forEach(inp => {
                        if ((inp.name||'').toLowerCase().includes('max') ||
                            (inp.id||'').toLowerCase().includes('max')) {
                            inp.value = '9999';
                        }
                    });

                    // Find Load button/link
                    const all = Array.from(document.querySelectorAll('a, input, button'));
                    const loadBtn = all.find(e => {
                        const t = (e.innerText||e.value||'').toLowerCase();
                        const oc = (e.getAttribute('onclick')||'').toLowerCase();
                        return t.includes('load') || oc.includes('load');
                    });

                    if (loadBtn) {
                        loadBtn.click();
                        return 'clicked: ' + (loadBtn.innerText||loadBtn.value||loadBtn.getAttribute('onclick'));
                    }

                    // Try form submit
                    const form = document.querySelector('form');
                    if (form) { form.submit(); return 'form submitted: ' + form.action; }

                    return 'nothing found — links: ' + all.map(e=>e.innerText||e.value).filter(t=>t).join(' | ');
                } catch(e) { return 'error: ' + e; }
            }""")
            print(f"    Result: {result}")
            await asyncio.sleep(8)
            await pg.screenshot(path=str(SS/'client_loaded.png'), full_page=True)

            # New requests
            new_reqs = {k: v for k, v in captured_reqs.items() if k not in before}
            print(f"\n[6] New requests: {len(new_reqs)}")
            for url, data in new_reqs.items():
                print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
                if data['body']:
                    print(f"         {data['body'][:200]}")

        # Check MainClientBody
        print(f"\n[7] Looking for client data in all frames...")
        for frame in pg.frames:
            if 'Client' in frame.url and 'Main/Home' not in frame.url:
                try:
                    text = await frame.inner_text('body')
                    if len(text.strip()) > 100:
                        print(f"\n    {frame.url.split('goctl.com')[1][:70]}")
                        print(f"    {text[:800]}")
                        html = await frame.content()
                        fname = frame.url.split('/')[-1].split('?')[0]
                        (OUT/f'client_result_{fname}.html').write_text(html)
                except: pass

        # Also try hitting MainClientBody directly
        print(f"\n[8] Hitting MainClientBody.aspx directly with Comet filter...")
        result = await pg.evaluate("""async () => {
            const r = await fetch('/Client/ClientFrame/ClientBody/MainClientBody.aspx?ClientID_First=0&ClientID_Last=0&Status=A&TerminalID=22&AccountNo=&TimezoneAbbrev=UTC&MaxRecords=9999');
            return {status: r.status, body: (await r.text()).substring(0, 2000)};
        }""")
        print(f"    Status: {result['status']}")
        print(f"    Body: {result['body'][:500]}")
        (OUT/'client_main_body.html').write_text(result['body'])

        await br.close()

asyncio.run(run())
