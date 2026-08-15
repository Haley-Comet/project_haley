import asyncio, os, json
from pathlib import Path
from datetime import datetime

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
                captured_reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:500]}
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
            print("ERROR: frame not found"); await br.close(); return

        # Dump the full HTML to understand the form
        html = await coll_frame.content()
        (OUT/'collections_full.html').write_text(html)
        print(f"    HTML saved: {len(html)} chars")

        # Find all clickable elements
        clickables = await coll_frame.evaluate("""() => {
            return Array.from(document.querySelectorAll('a, input[type=submit], input[type=button], button')).map(e => ({
                tag: e.tagName,
                text: e.innerText.trim() || e.value || '',
                href: e.href || '',
                onclick: (e.getAttribute('onclick') || '').substring(0,200),
                name: e.name || '',
                id: e.id || ''
            })).filter(e => e.text);
        }""")
        print(f"\n[3] All clickable elements:")
        for c in clickables:
            print(f"    {c['tag']} '{c['text']}' href={c['href'][:60]} onclick={c['onclick'][:80]}")

        # Get the form action and hidden fields
        form_info = await coll_frame.evaluate("""() => {
            const forms = Array.from(document.querySelectorAll('form')).map(f => ({
                action: f.action,
                method: f.method,
                hiddenFields: Array.from(f.querySelectorAll('input[type=hidden]')).map(i => ({
                    name: i.name, value: i.value.substring(0,50)
                }))
            }));
            return forms;
        }""")
        print(f"\n[4] Forms:")
        for f in form_info:
            print(f"    action={f['action']} method={f['method']}")
            for h in f['hiddenFields']:
                print(f"      hidden: {h['name']}={h['value'][:40]}")

        # Try clicking the Run Collections link directly
        print("\n[5] Clicking Run Collections...")
        before = set(captured_reqs.keys())

        # Select Comet terminal
        await coll_frame.evaluate("""() => {
            const sel = document.querySelector('select[name="Terminals"]');
            if (sel) {
                for (let opt of sel.options) {
                    opt.selected = opt.text.trim() === 'Comet';
                }
            }
        }""")

        # Click "Run Collections" link/button
        try:
            await coll_frame.click('text=Run Collections', timeout=5000)
            print("    Clicked via text=Run Collections")
        except:
            # Try by finding the link
            result = await coll_frame.evaluate("""() => {
                const all = Array.from(document.querySelectorAll('a, input, button'));
                const btn = all.find(e => (e.innerText||e.value||'').toLowerCase().includes('run'));
                if (btn) { btn.click(); return 'clicked: ' + (btn.innerText||btn.value); }
                return 'not found';
            }""")
            print(f"    JS click result: {result}")

        await asyncio.sleep(5)
        await pg.screenshot(path=str(SS/'collections_results.png'), full_page=True)

        # Check new requests
        new_reqs = {k: v for k, v in captured_reqs.items() if k not in before}
        print(f"\n[6] New requests after clicking Run: {len(new_reqs)}")
        for url, data in new_reqs.items():
            print(f"  {data['method']} {url.split('goctl.com')[1][:80]}")
            print(f"    Body: {data['body'][:200]}")

        # Read all frame text
        print("\n[7] Frame content after Run:")
        for frame in pg.frames:
            if 'Collections' in frame.url:
                try:
                    text = await frame.inner_text('body')
                    print(f"\n  {frame.url.split('goctl.com')[1]}")
                    print(f"  {text[:800]}")
                    html2 = await frame.content()
                    (OUT/f'coll_after_{frame.url.split("/")[-1].split("?")[0]}.html').write_text(html2)
                except: pass

        await br.close()

asyncio.run(run())
