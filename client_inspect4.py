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
        pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try:
                b = await r.text()
                captured[r.url] = b[:50000]
            except: pass
        pg.on('response', cap)

        print("[1] Logging in...")
        await login(pg)

        print("[2] Opening ClientMaster + loading all Comet clients...")
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

        # The key: POST to ClientBody.aspx with Comet filter
        # then read MainClientBody which should list clients with data
        print("\n[3] POSTing to ClientBody with Comet/Active filter...")
        before = set(captured.keys())

        result = await pg.evaluate("""async () => {
            const body = new URLSearchParams({
                ClientID_First: '0',
                ClientID_Last: '0',
                Status: 'A',
                TerminalID: '22',
                AccountNo: '',
                TimezoneAbbrev: 'UTC'
            });
            const r = await fetch('/Client/ClientFrame/ClientBody.aspx', {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: body.toString()
            });
            return {status: r.status, body: (await r.text()).substring(0, 500)};
        }""")
        print(f"    Status: {result['status']}")
        print(f"    Body preview: {result['body'][:300]}")

        # Now fetch MainClientBody with all params
        print("\n[4] Fetching MainClientBody with Comet filter...")
        result2 = await pg.evaluate("""async () => {
            const url = '/Client/ClientFrame/ClientBody/MainClientBody.aspx?ClientID_First=0&ClientID_Last=0&Status=A&TerminalID=22&AccountNo=&TimezoneAbbrev=UTC&MaxRecords=9999';
            const r = await fetch(url);
            return {status: r.status, body: await r.text()};
        }""")
        body_html = result2['body']
        (OUT/'main_client_body_comet.html').write_text(body_html)
        print(f"    Status: {result2['status']}, Size: {len(body_html)} chars")

        # Parse this HTML for client data
        # Look for account numbers and addresses in the HTML
        acct_matches = re.findall(r'AccountNo[=\s"\']+(\d+)', body_html)
        phone_matches = re.findall(r'Phone[^>]*>([^<]{7,20})', body_html)
        print(f"    Account numbers found: {acct_matches[:10]}")
        print(f"    Phones found: {phone_matches[:5]}")

        # Look at the raw text
        from html.parser import HTMLParser
        class TextParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
            def handle_data(self, data):
                d = data.strip()
                if d: self.text.append(d)
        parser = TextParser()
        parser.feed(body_html)
        text = '\n'.join(parser.text)
        (OUT/'main_client_body_text.txt').write_text(text)
        print(f"\n    Rendered text (first 1000 chars):")
        print(text[:1000])

        # Check if xApi/ClientMaster has a GET list endpoint
        print("\n[5] Checking if there's a client export/list xApi...")
        for ep in [
            '/xApi/ClientMaster/GetClientMaster?TerminalID=22&Status=A',
            '/xApi/ClientMaster/ExportClients?TerminalID=22',
            '/api/clientmaster/export?TerminalID=22&Status=A&Format=json',
            '/api/controls/getclientlist?TerminalID=22&Status=A',
            '/xApi/report/GetClientList?TerminalID=22',
        ]:
            r = await pg.evaluate(f"""async () => {{
                const r = await fetch('{ep}');
                const t = await r.text();
                return {{status: r.status, ct: r.headers.get('content-type'), body: t.substring(0,200)}};
            }}""")
            if r['status'] < 404:
                print(f"    {ep.split('?')[0].split('/')[-1]}: {r['status']} {r['ct']}")
                if r['body'].strip()[:1] in '[{':
                    print(f"    JSON! → {r['body'][:200]}")

        await br.close()

asyncio.run(run())
