import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
OUT  = Path('/opt/xcelerator/output')

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(4)

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(15000)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")

        # Fetch the erdereoverview JS to find API endpoints
        print("\n[2] Reading erdereoverview.js...")
        js = await pg.evaluate("""async () => {
            const r = await fetch('/Areas/Main/Scripts/Dashboard/erdereoverview.js');
            return await r.text();
        }""")
        (OUT/'erdereoverview.js').write_text(js)
        # Print lines containing 'api' or 'url'
        for line in js.split('\n'):
            if 'api' in line.lower() or 'url' in line.lower() or 'ajax' in line.lower():
                print(f"    {line.strip()[:120]}")

        # Also read the orderoverview page JS
        print("\n[3] Fetching known dashboard APIs with TerminalID=23...")
        import time
        ts = int(time.time() * 1000)
        apis = [
            f'/api/dashboard/gettotals7_p_TerminalID=23&_={ts}',
            f'/api/dashboard/ordersoverview?_={ts}',
            f'/api/dashboard/getdispatchstatus7?TerminalID=23&FromDate=04%2F01%2F2026&ToDate=04%2F03%2F2026&PML=_&_={ts}',
            # Try order list variants with TerminalID
            f'/api/distribution/getorderlist?TerminalID=23&_={ts}',
            f'/api/distribution/orderlist?TerminalID=23&_={ts}',
            f'/api/operations/getorderlist?TerminalID=23&_={ts}',
            f'/api/ordermanager/getorders?TerminalID=23&_={ts}',
            f'/api/dispatch/getorders?TerminalID=23&_={ts}',
            f'/api/dispatch/getorderlist?TerminalID=23&_={ts}',
            f'/api/orders/getbyterminial?TerminalID=23&_={ts}',
            f'/api/erdereoverview?TerminalID=23&_={ts}',
            f'/api/dashboard/geterdere?TerminalID=23&_={ts}',
            f'/api/dashboard/getActiveOrders?TerminalID=23&_={ts}',
            f'/api/dashboard/getorderdetails?TerminalID=23&_={ts}',
        ]
        for path in apis:
            try:
                result = await pg.evaluate(f"""async () => {{
                    const r = await fetch('{path}');
                    const text = await r.text();
                    return {{status: r.status, body: text.substring(0,300), isJson: text.trim().startsWith('[') || text.trim().startsWith('{{') }};
                }}""")
                marker = '✓ JSON' if result['isJson'] else ('✓ HTML' if result['status'] < 400 else '✗')
                if result['isJson']:
                    print(f"    {marker} {path.split('?')[0]}: {result['body'][:150]}")
                    (OUT/f"api_{path.split('/api/')[1].split('?')[0].replace('/','_')}.json").write_text(result['body'])
                elif result['status'] < 400 and not result['body'].strip().startswith('<!'):
                    print(f"    {marker} {path.split('?')[0]}: {result['body'][:100]}")
            except Exception as e:
                pass

        await br.close()

asyncio.run(run())
