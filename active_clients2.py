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
                captured_reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:300]}
            except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        print("\n[2] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(6)

        std_frame = next((f for f in pg.frames if 'standardreport' in f.url.lower()), None)
        print(f"    Std frame: {std_frame.url if std_frame else 'NOT FOUND'}")

        # Wait for the sr1_Frame subframe to load
        await asyncio.sleep(3)
        sub_frame = next((f for f in pg.frames if 'standardreportssubframe' in f.url.lower()), None)
        print(f"    Sub frame: {sub_frame.url if sub_frame else 'NOT FOUND'}")

        if sub_frame:
            text = await sub_frame.inner_text('body')
            print(f"\n[3] Subframe text:\n{text[:500]}")

            html = await sub_frame.content()
            (OUT/'sr_subframe.html').write_text(html)

            # Find report tree items
            tree_items = await sub_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('li, a, span, div')).map(e => ({
                    tag: e.tagName,
                    text: e.innerText.trim().substring(0,50),
                    onclick: (e.getAttribute('onclick')||'').substring(0,100),
                    id: e.id,
                    cls: e.className
                })).filter(e => e.text && e.text.length > 2 && e.text.length < 50)
            """)
            print(f"\n[4] Tree items ({len(tree_items)}):")
            for item in tree_items[:30]:
                print(f"    {item['tag']} '{item['text']}' {item['onclick'] or item['id']}")

        # Click Active Clients Report in the subframe
        print("\n[5] Clicking Active Clients Report...")
        before = set(captured_reqs.keys())
        before_resp = set(captured.keys())

        if sub_frame:
            result = await sub_frame.evaluate("""() => {
                const all = Array.from(document.querySelectorAll('*'));
                const target = all.find(e => (e.innerText||'').trim() === 'Active Clients Report');
                if (target) { target.click(); return 'clicked'; }

                // Try Kendo treeview
                const tv = $('#reportTree').data('kendoTreeView');
                if (tv) {
                    const nodes = tv.dataSource.data();
                    return 'kendo tree nodes: ' + nodes.length;
                }
                return 'not found';
            }""")
            print(f"    Result: {result}")
            await asyncio.sleep(6)
            await pg.screenshot(path=str(SS/'active_rpt_clicked.png'), full_page=True)

        new_reqs = {k:v for k,v in captured_reqs.items() if k not in before}
        new_resp = {k:v for k,v in captured.items() if k not in before_resp}

        print(f"\n[6] New requests: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"    {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"         {data['body'][:150]}")

        print(f"\n[7] New responses:")
        for url, body in new_resp.items():
            path = url.split('goctl.com')[1][:80]
            print(f"\n    {path} ({len(body)} chars)")
            if body.strip()[:1] in '[{':
                print(f"    JSON: {body[:300]}")
            else:
                clean = re.sub(r'<[^>]+>', ' ', body)
                clean = re.sub(r'\s+', ' ', clean).strip()
                print(f"    TEXT: {clean[:200]}")

        # Also check all frame text
        print(f"\n[8] All frames text after click:")
        for frame in pg.frames:
            if 'report' in frame.url.lower() or 'standard' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    if len(text.strip()) > 50:
                        print(f"\n    {frame.url.split('goctl.com')[1][:60]}")
                        print(f"    {text[:400]}")
                        html = await frame.content()
                        (OUT/f'rpt_{frame.url.split("/")[-1].split("?")[0]}.html').write_text(html)
                except: pass

        await br.close()

asyncio.run(run())
