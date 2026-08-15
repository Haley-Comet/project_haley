import asyncio, os, json, re
from pathlib import Path
import urllib.request

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
    captured = {}
    js_files = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def on_response(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured[r.url] = json.loads(b)
                # Capture JS files too
                if '.js' in r.url and 'frame' in r.url.lower():
                    js_files[r.url] = b
            except: pass

        pg.on('response', on_response)
        await login(pg)
        print("Logged in.")

        # Get frame.js content and search for Invoicing/OpenWindow patterns
        frame_js = None
        for url, content in js_files.items():
            print(f"Captured JS: {url} ({len(content)} chars)")
            if 'openwindow' in content.lower() or 'invoic' in content.lower():
                frame_js = content

        if frame_js:
            # Find OpenWindow calls related to invoicing/accounting
            matches = re.findall(r'OpenWindow[^;]{0,300}', frame_js, re.I)
            print("\n=== OpenWindow calls ===")
            for m in matches[:10]:
                print(m)

        # Try calling OpenWindow directly with candidate paths
        print("\n=== Trying OpenWindow calls ===")
        before = set(captured.keys())

        candidates = [
            ('Invoicing/Index', 'Invoicing'),
            ('Accounting/Invoicing', 'Invoicing'),
            ('Accounting/Invoicing/Index', 'Invoicing'),
            ('Invoice/Index', 'Invoice'),
            ('Accounting/Invoice/Index', 'Invoice'),
            ('Invoicing/InvoiceSetup', 'Invoicing'),
        ]

        for path, wid in candidates:
            try:
                result = await pg.evaluate(f"""
                    () => {{
                        if (typeof OpenWindow !== 'undefined') {{
                            OpenWindow('{path}', '{wid}', '{wid}', '', '', '', 0, 0);
                            return 'called OpenWindow({path})';
                        }}
                        return 'OpenWindow not found';
                    }}
                """)
                print(f"  {result}")
                await asyncio.sleep(3)
                new_reqs = [u for u in captured if u not in before]
                if new_reqs:
                    print(f"  NEW REQUESTS: {new_reqs}")
                    before = set(captured.keys())
                    break
            except Exception as e:
                print(f"  Error: {e}")

        # Also dump all window open* functions source
        print("\n=== openInvoic* or openAcct* functions ===")
        funcs = await pg.evaluate("""
            () => {
                const result = {};
                for (const k in window) {
                    if (typeof window[k] === 'function' && 
                        (k.toLowerCase().includes('invoic') || 
                         k.toLowerCase().includes('acct') ||
                         k.toLowerCase().includes('billing') ||
                         k.toLowerCase().includes('statement'))) {
                        result[k] = window[k].toString().slice(0, 300);
                    }
                }
                return result;
            }
        """)
        print(json.dumps(funcs, indent=2))

        # Check all frames for Invoicing content
        print("\n=== Non-blank frames ===")
        for f in pg.frames:
            if f.url != 'about:blank' and 'goctl.com' in f.url:
                print(f"  {f.url}")

        await br.close()

asyncio.run(run())
