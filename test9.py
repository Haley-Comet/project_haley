import asyncio, os, json
from pathlib import Path
from datetime import datetime, timedelta

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
OUT  = Path('/opt/xcelerator/output')

today = datetime.now().strftime('%m%%2F%d%%2F%Y')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%m%%2F%d%%2F%Y')

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(4)

async def api(pg, path):
    result = await pg.evaluate(f"""async () => {{
        const r = await fetch('{path}');
        const text = await r.text();
        return {{status: r.status, body: text.substring(0, 1000)}};
    }}""")
    return result

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(15000)

        # Capture ALL API calls while navigating
        all_api_calls = {}
        async def capture(response):
            url = response.url
            if '/api/' in url and 'goctl.com' in url:
                try:
                    body = await response.text()
                    if body.strip().startswith('[') or body.strip().startswith('{'):
                        all_api_calls[url.split('?')[0]] = body[:500]
                except: pass
        pg.on('response', capture)

        print("[1] Logging in...")
        await login(pg)

        # Call known working APIs from image 2
        print("\n[2] Calling confirmed APIs...")
        confirmed = [
            f'/api/dashboard/gettotals7_p_TerminalID=23',
            f'/api/dashboard/ordersoverview',
            f'/api/dashboard/getdispatchstatus7?TerminalID=23&FromDate={yesterday}&ToDate={today}&PML=_',
            f'/api/dashboardchart/getccsorderscount7?TerminalID=23&FromDate={yesterday}&ToDate={today}&PML=_',
            f'/api/dashboard/getrevenuebymonth7?TerminalID=23&FromDate={yesterday}&ToDate={today}&PML=_',
        ]
        for path in confirmed:
            r = await api(pg, path)
            print(f"\n  {path.split('?')[0]}:")
            print(f"  {r['body'][:200]}")
            (OUT/f"confirmed_{path.split('api/')[1].split('?')[0].replace('/','_')}.json").write_text(r['body'])

        # Now try to navigate to Distribution section and intercept API calls
        print("\n[3] Navigating inside app to capture order list API...")
        await pg.goto('https://www.goctl.com/Main/Distribution', wait_until='load')
        await asyncio.sleep(3)
        print(f"    URL: {pg.url}")

        await pg.goto('https://www.goctl.com/Main/Operations', wait_until='load')
        await asyncio.sleep(3)
        print(f"    URL: {pg.url}")

        print(f"\n[4] All JSON API calls captured ({len(all_api_calls)}):")
        for url, body in all_api_calls.items():
            print(f"  {url}")
            print(f"    {body[:100]}")
        (OUT/'all_captured_apis.json').write_text(json.dumps(all_api_calls, indent=2))

        await br.close()

asyncio.run(run())
