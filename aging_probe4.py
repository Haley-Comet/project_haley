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
    captured_reqs = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:10000]
            except: pass

        async def cap_req(r):
            if 'goctl.com' not in r.url: return
            try:
                captured_reqs[r.url] = {'method': r.method, 'body': r.post_data or ''}
            except: pass

        pg.on('response', cap_resp)
        pg.on('request', cap_req)

        print("[1] Logging in...")
        await login(pg)

        print("\n[2] Opening Collections frame...")
        await pg.evaluate("() => { openFrame('Collections'); }")
        await asyncio.sleep(6)

        coll_frame = next((f for f in pg.frames if 'Collections.aspx' in f.url), None)
        if not coll_frame:
            print("    Collections frame not found")
            await br.close()
            return

        print(f"    Found: {coll_frame.url}")

        # Select Comet terminal only
        print("\n[3] Selecting Comet terminal and running collections...")
        await coll_frame.evaluate("""() => {
            // Deselect all terminals, select only Comet
            const terminals = document.querySelector('select[name="Terminals"]');
            if (terminals) {
                for (let opt of terminals.options) {
                    opt.selected = opt.text.trim().includes('Comet');
                }
            }
            // Set minimum days late to 30
            const daysLate = document.querySelector('input[name="DaysLate"]') ||
                             document.querySelector('input[name="DaysMin"]');
            if (daysLate) daysLate.value = '1';

            // Set minimum amount to 0
            const minAmt = document.querySelector('input[name="MinAmt"]') ||
                           document.querySelector('input[name="MinimumAmount"]') ||
                           document.querySelector('input[name="MinAmount"]');
            if (minAmt) minAmt.value = '0';
        }""")

        await pg.screenshot(path=str(SS/'collections_before_run.png'), full_page=True)

        # Click Run Collections button
        before_keys = set(captured.keys())
        before_req_keys = set(captured_reqs.keys())

        run_result = await coll_frame.evaluate("""() => {
            // Find and click Run Collections button
            const buttons = Array.from(document.querySelectorAll('input[type="submit"], input[type="button"], button'));
            const runBtn = buttons.find(b => b.value && b.value.toLowerCase().includes('run') ||
                                            b.innerText && b.innerText.toLowerCase().includes('run'));
            if (runBtn) {
                runBtn.click();
                return 'clicked: ' + (runBtn.value || runBtn.innerText);
            }
            return 'button not found — buttons: ' + buttons.map(b => b.value || b.innerText).join(', ');
        }""")
        print(f"    Button click result: {run_result}")

        await asyncio.sleep(6)
        await pg.screenshot(path=str(SS/'collections_after_run.png'), full_page=True)

        # Check new responses
        new_resps = {k: v for k, v in captured.items() if k not in before_keys}
        new_reqs  = {k: v for k, v in captured_reqs.items() if k not in before_req_keys}

        print(f"\n[4] New requests after Run Collections: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"  {data['method']} {url.split('goctl.com')[1][:80]}")
            if data['body']:
                print(f"       Body: {data['body'][:200]}")

        print(f"\n[5] New responses: {len(new_resps)}")
        for url, body in new_resps.items():
            path = url.split('goctl.com')[1][:80]
            if body.strip()[:1] in '[{':
                print(f"\n  JSON: {path}")
                print(f"  {body[:400]}")
            else:
                print(f"\n  Page: {path} ({len(body)} chars)")
                # Print text content if it looks like data
                if any(x in path.lower() for x in ['collect', 'aging', 'result', 'report', 'ar']):
                    print(f"  Content: {body[:500]}")
            (OUT/f'coll_{path.replace("/","_").strip("_")}.html').write_text(body)

        # Also read the frame text after running
        print("\n[6] Collections frame text after Run:")
        for frame in pg.frames:
            if 'Collections' in frame.url or 'collection' in frame.url.lower():
                try:
                    text = await frame.inner_text('body')
                    print(f"  Frame {frame.url.split('goctl.com')[1][:60]}:")
                    print(f"  {text[:600]}")
                    html = await frame.content()
                    (OUT/f'coll_frame_{frame.url.split("/")[-1]}.html').write_text(html)
                except: pass

        await br.close()

asyncio.run(run())
