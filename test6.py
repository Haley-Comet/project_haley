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
    await asyncio.sleep(4)

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(15000)

        # Capture all network requests
        requests_log = []
        pg.on('request', lambda r: requests_log.append(r.url) if 'goctl' in r.url else None)

        print("[1] Logging in...")
        await login(pg)
        print(f"    On: {pg.url}")

        # Dump the full page HTML — nav is in there even if JS-rendered
        html = await pg.content()
        (OUT/'main_home_full.html').write_text(html)
        print(f"    HTML saved ({len(html)} chars)")

        # Get ALL href values including data attrs
        all_hrefs = await pg.evaluate("""() => {
            const results = [];
            document.querySelectorAll('[href],[data-url],[data-href],[data-link]').forEach(el => {
                results.push({
                    tag: el.tagName,
                    text: el.innerText.trim().substring(0,40),
                    href: el.getAttribute('href') || '',
                    dataUrl: el.getAttribute('data-url') || '',
                    dataHref: el.getAttribute('data-href') || '',
                    onclick: (el.getAttribute('onclick') || '').substring(0,100)
                });
            });
            return results;
        }""")
        (OUT/'all_hrefs.json').write_text(json.dumps(all_hrefs, indent=2))
        print(f"    Elements with href/data attrs: {len(all_hrefs)}")
        for el in all_hrefs:
            print(f"      {el['tag']} '{el['text']}' href={el['href']} onclick={el['onclick'][:60]}")

        # Log all network requests made so far
        print(f"\n    Network requests to goctl.com: {len(requests_log)}")
        for r in requests_log:
            print(f"      {r}")

        await br.close()

asyncio.run(run())
