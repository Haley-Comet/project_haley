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

async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        # Login
        print("[1] Logging in...")
        await pg.goto('https://www.goctl.com/account/Account/login', wait_until='networkidle')
        for sel in ['input[name="UserName"]','input[type="text"]']:
            try:
                el = await pg.query_selector(sel)
                if el and await el.is_visible(): await el.fill(USER); break
            except: pass
        for sel in ['input[name="Password"]','input[type="password"]']:
            try:
                el = await pg.query_selector(sel)
                if el and await el.is_visible(): await el.fill(PASS); break
            except: pass
        for sel in ['button[type="submit"]','input[type="submit"]']:
            try:
                el = await pg.query_selector(sel)
                if el: await el.click(); break
            except: pass
        await pg.wait_for_load_state('networkidle')
        print(f"    Post-login: {pg.url}")

        # Go to Main/home
        print("[2] Loading Main/home...")
        await pg.goto('https://www.goctl.com/Main/home', wait_until='networkidle')
        await pg.screenshot(path=str(SS/'main_home.png'), full_page=True)
        print(f"    URL: {pg.url}")

        # Dump all links
        links = await pg.evaluate("""() => Array.from(document.querySelectorAll('a')).map(e=>({
            text: e.innerText.trim().replace(/\s+/g,' '),
            href: e.href
        })).filter(l=>l.text&&l.href&&!l.href.startsWith('javascript'))""")
        (OUT/'main_links.json').write_text(json.dumps(links, indent=2))
        print(f"    Links: {len(links)}")

        # Dump all tables
        tables = await pg.evaluate("""() => {
            return Array.from(document.querySelectorAll('table')).map((t,i) => {
                const headers = Array.from(t.querySelectorAll('th')).map(h=>h.innerText.trim());
                const rows = Array.from(t.querySelectorAll('tr')).slice(0,5).map(r=>
                    Array.from(r.querySelectorAll('td,th')).map(c=>c.innerText.trim().substring(0,50))
                );
                return { table_index: i, headers, sample_rows: rows };
            });
        }""")
        (OUT/'main_tables.json').write_text(json.dumps(tables, indent=2))
        print(f"    Tables: {len(tables)}")
        for t in tables:
            print(f"      Table {t['table_index']}: headers={t['headers']}")

        # Dump page text (top 3000 chars)
        text = await pg.inner_text('body')
        (OUT/'main_page_text.txt').write_text(text[:5000])
        print(f"    Page text (first 500 chars):\n{text[:500]}")

        # Save full HTML
        (OUT/'main_home.html').write_text(await pg.content())

        print("\n=== DONE ===")
        print("Share: cat /opt/xcelerator/output/main_tables.json")
        await br.close()

asyncio.run(run())
