import asyncio, os, json
from pathlib import Path

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
                        popup_captured[r.url] = b[:200]
                except: pass
            popup.on('response', on_resp)

        ctx.on('page', on_popup)

        await login(pg)
        print("Logged in.")

        # Try just the relativePath with empty WindowPath
        candidates = [
            ('Accounting/Invoicing/Index', ''),
            ('Accounting/Invoicing', ''),
            ('Accounting/Invoicing/Index', 'Accounting/Invoicing/Index'),
        ]

        for rel, path in candidates:
            popup_pages.clear()
            popup_captured.clear()
            win_path = path if path else rel

            print(f"\nTrying rel='{rel}' path='{path}'")
            try:
                await pg.evaluate(f"""
                    () => OpenWindow('{rel}', 'InvWin', 'Invoicing', '{path}',
                        'toolbar=no,scrollbars=yes,width=1200,height=800', '', 100, 100)
                """)
            except Exception as e:
                print(f"  Error: {e}")
                continue

            await asyncio.sleep(6)

            if popup_pages:
                pp = popup_pages[0]
                print(f"  Final URL: {pp.url}")
                try:
                    await pp.wait_for_load_state('load', timeout=10000)
                    title = await pp.title()
                    print(f"  Title: {title}")

                    # Get all API calls
                    api = [u for u in popup_captured if '/api/' in u]
                    print(f"  API calls ({len(api)}): {api[:5]}")
                    for u in api[:3]:
                        print(f"    {u}")
                        print(f"    {json.dumps(popup_captured[u])[:300]}")

                    # Check frames in popup
                    print(f"  Popup frames: {[f.url for f in pp.frames if f.url != 'about:blank']}")

                    # Get page HTML snippet
                    html = await pp.content()
                    print(f"  HTML ({len(html)} chars): {html[500:1500]}")

                except Exception as e:
                    print(f"  Wait error: {e}")

                # Close popup and try next
                try: await pp.close()
                except: pass
            else:
                print("  No popup")

        await br.close()

asyncio.run(run())
