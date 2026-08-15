import asyncio, os, json
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
TEST_ACCT = 10016  # Kirkland & Ellis

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(8)

async def run():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await br.new_context(viewport={'width':1440,'height':900})
        pg = await ctx.new_page()
        pg.set_default_timeout(30000)

        popup_pages = []
        popup_captured = {}

        async def on_popup(popup):
            popup_pages.append(popup)
            print(f"  POPUP: {popup.url}")
            async def on_resp(r):
                if 'goctl.com' not in r.url: return
                try:
                    b = await r.text()
                    if b.strip()[:1] in '[{':
                        popup_captured[r.url] = json.loads(b)
                    else:
                        popup_captured[r.url] = b[:100]
                except: pass
            popup.on('response', on_resp)

        ctx.on('page', on_popup)

        await login(pg)
        print("Logged in.")

        # Get full OpenWindow signature
        sig = await pg.evaluate("() => typeof OpenWindow !== 'undefined' ? OpenWindow.toString().slice(0,800) : 'not found'")
        print(f"\nOpenWindow:\n{sig[:400]}\n")

        # Try opening ClientMaster with account number
        candidates = [
            ('Accounting/ClientMaster/Index', ''),
            ('ClientMaster/Index', ''),
            ('Accounting/Clients/Index', ''),
            ('Clients/Index', ''),
        ]

        for rel, path in candidates:
            popup_pages.clear()
            popup_captured.clear()

            print(f"\nTrying: {rel}")
            try:
                await pg.evaluate(f"""
                    () => OpenWindow('{rel}', 'ClientWin', 'Clients', '{path or rel}',
                        'toolbar=no,scrollbars=yes,width=1200,height=800', '', 100, 100)
                """)
            except Exception as e:
                print(f"  Error: {e}")
                continue

            await asyncio.sleep(5)

            if popup_pages:
                pp = popup_pages[0]
                print(f"  URL: {pp.url}")
                try:
                    await pp.wait_for_load_state('load', timeout=10000)
                    title = await pp.title()
                    print(f"  Title: {title}")
                    api = [u for u in popup_captured if '/api/' in u]
                    print(f"  API calls: {api[:5]}")
                    for u in api[:3]:
                        print(f"    {u}")
                        v = popup_captured[u]
                        print(f"    {json.dumps(v)[:300] if isinstance(v, (dict,list)) else v}")
                    if not api:
                        html = await pp.content()
                        print(f"  HTML snippet: {html[500:1500]}")
                except Exception as e:
                    print(f"  Error: {e}")
                try: await pp.close()
                except: pass
                if [u for u in popup_captured if '/api/' in u]:
                    break
            else:
                print("  No popup")

        await br.close()

asyncio.run(run())
