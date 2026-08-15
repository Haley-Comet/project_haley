import asyncio, os, json
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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:200000]
            except: pass
        pg.on('response', cap_resp)

        print("[1] Logging in...")
        await login(pg)

        # Get full report list
        print("\n[2] Fetching full report list...")
        result = await pg.evaluate("""async () => {
            const r = await fetch('/api/reportlist/GetReports');
            return await r.text();
        }""")
        (OUT/'report_list.json').write_text(result)
        try:
            data = json.loads(result)
            print(f"    Response size: {len(result)} chars")
            # Find client-related reports
            def find_reports(node, path=''):
                if isinstance(node, dict):
                    text = node.get('text','') or node.get('name','') or node.get('title','')
                    if any(x in text.lower() for x in ['client','customer','account','address']):
                        print(f"    FOUND: {path}/{text}")
                        print(f"           {json.dumps(node)[:200]}")
                    for k,v in node.items():
                        find_reports(v, f"{path}/{k}")
                elif isinstance(node, list):
                    for i,item in enumerate(node):
                        find_reports(item, f"{path}[{i}]")
            find_reports(data)
        except:
            print(f"    Raw: {result[:500]}")

        # Open Standard Reports
        print("\n[3] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(6)

        std_frame = next((f for f in pg.frames if 'standardreport' in f.url.lower()), None)
        if std_frame:
            html = await std_frame.content()
            (OUT/'std_reports.html').write_text(html)

            # Get the full JS to understand ExportVisibleReport
            scripts = await std_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('script:not([src])')).map(s => s.innerHTML.substring(0,2000))
            """)
            for s in scripts:
                if 'export' in s.lower() or 'report' in s.lower() or 'url' in s.lower():
                    print(f"\n    Inline JS:\n{s[:500]}")

            # Read all script src files
            script_srcs = await std_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('script[src]')).map(s => s.src).filter(s => s.includes('goctl'))
            """)
            for src in script_srcs:
                print(f"    Script: {src.split('goctl.com')[1].split('?')[0]}")

            # Try clicking on different report categories to find client list
            links = await std_frame.evaluate("""() =>
                Array.from(document.querySelectorAll('a, li, div')).map(e => ({
                    text: e.innerText.trim().substring(0,60),
                    onclick: (e.getAttribute('onclick')||'').substring(0,100),
                    href: (e.href||'').substring(0,80),
                    id: e.id
                })).filter(e => e.text && e.text.length > 2 && e.text.length < 60)
            """)
            print(f"\n    All clickable items ({len(links)}):")
            for l in links[:30]:
                print(f"    '{l['text']}' {l['onclick'] or l['href']}")

        await br.close()

asyncio.run(run())
