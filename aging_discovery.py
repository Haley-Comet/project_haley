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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    key = r.url.split('goctl.com')[1].split('?')[0]
                    captured[key] = {'url': r.url, 'body': b[:5000]}
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")

        # Dump all nav links from main page to find Accounting submenu
        print("\n[2] Reading nav structure...")
        nav = await pg.evaluate("""() => {
            return Array.from(document.querySelectorAll('[onclick]')).map(e => ({
                text: e.innerText.trim().replace(/\s+/g,' '),
                onclick: (e.getAttribute('onclick') || '').substring(0,120)
            })).filter(e => e.text.length > 0 && e.text.length < 50);
        }""")
        for item in nav:
            print(f"    '{item['text']}' → {item['onclick']}")

        # Try opening Accounting frames
        print("\n[3] Trying Accounting-related openFrame calls...")
        accounting_frames = [
            'AgingReport', 'Aging', 'AR', 'ARaging', 'AccountsReceivable',
            'InvoiceAging', 'CustomerAging', 'Invoices', 'Invoice',
            'AccountingReport', 'Reports', 'ARReport'
        ]
        for fname in accounting_frames:
            try:
                result = await pg.evaluate(f"""() => {{
                    try {{
                        openFrame('{fname}');
                        return 'called';
                    }} catch(e) {{ return 'error: ' + e; }}
                }}""")
                if result == 'called':
                    await asyncio.sleep(3)
                    # Check if any new frames loaded
                    for frame in pg.frames:
                        if 'goctl.com' in frame.url and 'home' not in frame.url.lower() and 'dashboard' not in frame.url.lower():
                            if frame.url not in ['https://www.goctl.com/Main/home']:
                                print(f"    ✓ openFrame('{fname}') → frame: {frame.url}")
                    await pg.screenshot(path=str(SS/f'aging_{fname}.png'), full_page=True)
            except: pass

        # Try the accounting page directly
        print("\n[4] Probing Accounting URLs directly...")
        probes = [
            '/Main/Accounting', '/Main/Accounting/AgingReport',
            '/Main/Accounting/Aging', '/Main/Accounting/ARReport',
            '/Main/Accounting/Invoices', '/Main/Reports',
            '/Accounting/Aging', '/Accounting/ARReport',
            '/api/accounting/aging', '/api/aging',
            '/api/invoices/aging', '/api/ar/aging',
        ]
        for path in probes:
            try:
                r = await pg.goto(f'https://www.goctl.com{path}', wait_until='domcontentloaded', timeout=6000)
                if r and r.status < 400 and 'login' not in pg.url.lower():
                    print(f"    ✓ {pg.url}")
                    await pg.screenshot(path=str(SS/f'aging_probe_{path.replace("/","_")}.png'))
                    (OUT/f'aging_{path.replace("/","_")}.html').write_text(await pg.content())
            except: pass

        # Show all captured JSON APIs
        print(f"\n[5] JSON APIs captured: {len(captured)}")
        for k, v in captured.items():
            if any(x in k.lower() for x in ['aging', 'invoice', 'ar', 'account', 'report']):
                print(f"\n  {k}")
                print(f"  {v['body'][:200]}")

        (OUT/'aging_captured.json').write_text(json.dumps({k: v['body'] for k,v in captured.items()}, indent=2))
        print("\nAll captured API paths:")
        for k in sorted(captured.keys()):
            print(f"  {k}")
        await br.close()

asyncio.run(run())
