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
    captured_main = {}
    popup_requests = []
    popup_captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = await br.new_context(viewport={'width':1440,'height':900})
        pg = await ctx.new_page()
        pg.set_default_timeout(30000)

        async def on_response(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    captured_main[r.url] = json.loads(b)
            except: pass

        pg.on('response', on_response)

        # Listen for popups at context level
        popup_page = None
        async def on_popup(popup):
            nonlocal popup_page
            popup_page = popup
            print(f"POPUP OPENED: {popup.url}")

            async def on_popup_response(r):
                popup_requests.append(r.url)
                try:
                    b = await r.text()
                    if b.strip()[:1] in '[{':
                        popup_captured[r.url] = json.loads(b)
                except: pass

            popup.on('response', on_popup_response)

        ctx.on('page', on_popup)
        pg.on('popup', on_popup)

        await login(pg)
        print("Logged in. Opening Invoicing window...")

        # Get the full OpenWindow signature from frame.js
        sig = await pg.evaluate("""
            () => typeof OpenWindow !== 'undefined' ? OpenWindow.toString().slice(0, 500) : 'not found'
        """)
        print(f"\nOpenWindow signature:\n{sig}\n")

        # Try several path combinations for Invoicing
        paths_to_try = [
            ('Accounting/Invoicing/Index', 'Accounting/Invoicing/Index'),
            ('Accounting/Invoicing/Invoicing', 'Accounting/Invoicing/Invoicing'),
            ('Invoicing/Index', 'Invoicing/Index'),
            ('Accounting/Invoice/Index', 'Accounting/Invoice/Index'),
            ('Invoicing/Invoicing', 'Invoicing/Invoicing'),
        ]

        for rel, path in paths_to_try:
            popup_page = None
            popup_requests.clear()
            popup_captured.clear()

            print(f"\nTrying: {path}")
            await pg.evaluate(f"""
                () => OpenWindow('{rel}', 'InvWin', 'Invoicing', '{path}',
                    'toolbar=no,scrollbars=yes,resizeable=yes,width=1200,height=800',
                    '', 0, 0)
            """)
            await asyncio.sleep(4)

            if popup_page:
                print(f"  Popup URL: {popup_page.url}")
                print(f"  Popup requests: {popup_requests[:5]}")
                api_calls = [u for u in popup_captured if '/api/' in u]
                print(f"  API calls: {api_calls}")
                if api_calls:
                    for u in api_calls[:3]:
                        print(f"    {u}: {json.dumps(popup_captured[u])[:200]}")
                    break
                # Try getting page content
                try:
                    title = await popup_page.title()
                    print(f"  Title: {title}")
                    html = await popup_page.content()
                    print(f"  HTML snippet: {html[1000:2000]}")
                except: pass
            else:
                print("  No popup detected")

        await br.close()

asyncio.run(run())
