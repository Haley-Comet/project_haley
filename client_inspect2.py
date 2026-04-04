import asyncio, os
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

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("[1] Logging in...")
        await login(pg)

        print("[2] Opening ClientMaster + Comet clients...")
        await pg.evaluate("() => { openFrame('ClientMaster'); }")
        await asyncio.sleep(6)

        panel = next((f for f in pg.frames
                      if 'Panel.aspx' in f.url and 'Client' in f.url and 'Top' not in f.url), None)
        await panel.evaluate("""() => {
            document.getElementById('TerminalID').value = '22';
            document.getElementById('Status').value = 'A';
            document.getElementById('MaxRecords').value = '9999';
            document.loadtoolbarform.submit();
        }""")
        await asyncio.sleep(6)

        # Open Kirkland & Ellis (ID 3155) via oCM - exactly as Jim does
        print("\n[3] Opening Kirkland profile via oCM(3155)...")
        await pg.evaluate("() => { window.top.oCM(3155); }")
        await asyncio.sleep(5)
        await pg.screenshot(path=str(SS/'oCM_kirkland.png'), full_page=True)

        print("\n[4] All frames after oCM:")
        for frame in pg.frames:
            if 'goctl.com' in frame.url and 'Main/Home' not in frame.url:
                try:
                    text = await frame.inner_text('body')
                    if len(text.strip()) > 30:
                        print(f"\n  {frame.url.split('goctl.com')[1][:70]}")
                        print(f"  {text[:600]}")
                        html = await frame.content()
                        fname = frame.url.split('/')[-1].split('?')[0]
                        (OUT/f'oCM_{fname}.html').write_text(html)
                except: pass

        # Try opening the addresses frame directly
        print("\n[5] Opening Addresses for Kirkland...")
        await pg.evaluate("() => { window.top.Ladd(3155, 'Kirkland & Ellis LLP'); }")
        await asyncio.sleep(4)

        for frame in pg.frames:
            if 'Address' in frame.url or 'address' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    if text.strip():
                        print(f"\n  {frame.url.split('goctl.com')[1][:70]}")
                        print(f"  {text[:600]}")
                        html = await frame.content()
                        (OUT/f'addresses_{frame.url.split("/")[-1].split("?")[0]}.html').write_text(html)
                except: pass

        await br.close()

asyncio.run(run())
