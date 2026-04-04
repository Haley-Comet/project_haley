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

async def probe_frame(pg, frame_name, captured, known_keys):
    print(f"\n--- openFrame('{frame_name}') ---")
    before_keys = set(captured.keys())

    await pg.evaluate(f"() => {{ openFrame('{frame_name}'); }}")
    await asyncio.sleep(8)

    # Screenshot
    await pg.screenshot(path=str(SS/f'acct_{frame_name}.png'), full_page=True)

    # List all frames
    for frame in pg.frames:
        if 'goctl.com' in frame.url and frame.url not in ['https://www.goctl.com/Main/home', 'https://www.goctl.com/Main/Home/Dashboard']:
            print(f"  Frame: {frame.url}")

    # New APIs since we opened this frame
    new_keys = set(captured.keys()) - before_keys - known_keys
    print(f"  New JSON APIs: {len(new_keys)}")
    for k in new_keys:
        print(f"    {k}")
        print(f"    {captured[k]['body'][:200]}")

    return new_keys

async def run():
    from playwright.async_api import async_playwright
    captured = {}
    known_keys = set()

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
        known_keys = set(captured.keys())

        # Probe AcctRec
        new1 = await probe_frame(pg, 'AcctRec', captured, known_keys)

        # Now find the AcctRec subframe and try to read its JS
        print("\n[2] Reading AcctRec frame JS files...")
        for frame in pg.frames:
            if 'acct' in frame.url.lower() or 'ar' in frame.url.lower() or 'aging' in frame.url.lower():
                print(f"  Probing frame: {frame.url}")
                try:
                    scripts = await frame.evaluate("""() =>
                        Array.from(document.querySelectorAll('script[src]'))
                            .map(s => s.src)
                            .filter(s => s.includes('goctl'))
                    """)
                    for s in scripts:
                        print(f"    script: {s}")
                except: pass

        # Probe Collections
        known_keys2 = set(captured.keys())
        new2 = await probe_frame(pg, 'Collections', captured, known_keys2)

        # Save everything
        (OUT/'acct_captured.json').write_text(json.dumps({k: v['body'] for k,v in captured.items()}, indent=2))
        print("\n\nAll frames at end:")
        for frame in pg.frames:
            if 'goctl.com' in frame.url:
                print(f"  {frame.url}")

        await br.close()

asyncio.run(run())
