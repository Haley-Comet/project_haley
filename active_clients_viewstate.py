import asyncio, os, json, re
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
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(60000)

        async def cap_resp(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:500000]
            except: pass
        pg.on('response', cap_resp)

        print("[1] Logging in...")
        await login(pg)

        print("[2] Opening Standard Reports...")
        await pg.evaluate("() => { openFrame('StandardRep'); }")
        await asyncio.sleep(10)

        # Find frames
        sub_frame = None
        for frame in pg.frames:
            if 'standardreportssubframe' in frame.url.lower():
                sub_frame = frame
                break

        print(f"    Subframe: {sub_frame.url if sub_frame else 'NOT FOUND'}")
        if not sub_frame:
            print("ERROR: subframe not found")
            await br.close()
            return

        # Fetch the report page FROM WITHIN the subframe context
        print("\n[3] Fetching ActiveClientsReport.aspx from subframe context...")
        result = await sub_frame.evaluate("""async () => {
            try {
                const r = await fetch('ActiveClientsReport.aspx');
                const html = await r.text();
                return {status: r.status, len: html.length, preview: html.substring(0, 300)};
            } catch(e) { return {error: e.toString()}; }
        }""")
        print(f"    Status: {result.get('status')} Len: {result.get('len')} Error: {result.get('error','')}")
        print(f"    Preview: {result.get('preview','')[:200]}")

        if result.get('status') == 200 and result.get('len', 0) > 2000:
            # Get full HTML
            full_html = await sub_frame.evaluate("""async () => {
                const r = await fetch('ActiveClientsReport.aspx');
                return await r.text();
            }""")
            (OUT/'active_clients_get.html').write_text(full_html)
            print(f"\n    Full HTML saved: {len(full_html)} chars")

            # Extract all form inputs
            inputs = re.findall(r'<input[^>]+name="([^"]+)"[^>]*value="([^"]*)"', full_html, re.I)
            selects = re.findall(r'<select[^>]+name="([^"]+)"', full_html, re.I)
            print(f"\n    Form inputs: {len(inputs)}")
            for name, val in inputs[:20]:
                print(f"    {name} = {val[:50]}")
            print(f"\n    Select fields: {selects}")

            # Look for ViewState
            vs = re.search(r'id="__VIEWSTATE"[^>]+value="([^"]+)"', full_html, re.I)
            print(f"\n    ViewState: {'FOUND (' + str(len(vs.group(1))) + ' chars)' if vs else 'NOT FOUND'}")

            # Build POST body from form
            post_data = {name: val for name, val in inputs}
            post_data['TerminalID'] = '22'  # Comet

            print(f"\n[4] POSTing form with TerminalID=22...")
            post_result = await sub_frame.evaluate("""async (data) => {
                const body = new URLSearchParams(data);
                const r = await fetch('ActiveClientsReport.aspx', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: body.toString()
                });
                const text = await r.text();
                return {status: r.status, len: text.length, preview: text.substring(0, 500)};
            }""", post_data)
            print(f"    Status: {post_result['status']} Len: {post_result['len']}")
            print(f"    Preview: {post_result['preview'][:300]}")

            if post_result['len'] > 5000:
                full_post = await sub_frame.evaluate("""async (data) => {
                    const body = new URLSearchParams(data);
                    const r = await fetch('ActiveClientsReport.aspx', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: body.toString()
                    });
                    return await r.text();
                }""", post_data)
                (OUT/'active_clients_post.html').write_text(full_post)
                clean = re.sub(r'<[^>]+>', ' ', full_post)
                clean = re.sub(r'\s+', ' ', clean).strip()
                print(f"\n    POST text:\n{clean[:1000]}")
        else:
            print("\n    GET failed — Excelerator blocks this path")
            print("    → Fall back to Option 1: Jim exports manually")

        await br.close()

asyncio.run(run())
