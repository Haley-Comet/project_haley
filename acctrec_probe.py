#!/usr/bin/env python3
# acctrec_probe.py — READ-ONLY goctl discovery. No DB writes.
# Goal: find where per-account invoice detail / aging buckets live.
# Dumps to /opt/xcelerator/output/acctrec_probe.json and prints a summary.
import asyncio, os, json, re
from datetime import datetime
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
OUT  = Path('/opt/xcelerator/output')
resp = {}   # url -> text (truncated)
reqs = {}   # url -> {method, body}

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=40)
    await pg.type('input[name="Password"]', PASS, delay=40)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load'); await asyncio.sleep(5)

async def run():
    from playwright.async_api import async_playwright
    out = {'ts': datetime.now().isoformat(), 'menu_openframe': [], 'frames': [],
           'collections_row_html': [], 'json_endpoints': [], 'acctrec': {}}
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900}); pg.set_default_timeout(30000)

        async def cap(r):
            if 'goctl.com' not in r.url: return
            try: resp[r.url] = (await r.text())[:4000]
            except: pass
        def capreq(r):
            if 'goctl.com' in r.url and r.method == 'POST':
                try: reqs[r.url] = {'method': r.method, 'body': (r.post_data or '')[:400]}
                except: pass
        pg.on('response', cap); pg.on('request', capreq)

        print("login..."); await login(pg)

        # 1) enumerate the menu — every openFrame('X') the home page exposes
        menu = await pg.evaluate(r"""() => {
            const s = new Set();
            document.querySelectorAll('*').forEach(el => {
                const h = el.getAttribute && el.getAttribute('onclick');
                if (h) { const m = h.match(/openFrame\(['"]([^'"]+)['"]/); if (m) s.add(m[1]); }
            });
            (document.documentElement.innerHTML.match(/openFrame\(['"][^'"]+['"]/g)||[])
                .forEach(x => s.add(x.replace(/openFrame\(['"]/,'').replace(/['"]/,'')));
            return [...s];
        }""")
        out['menu_openframe'] = sorted(menu)
        print("menu openFrame targets:", out['menu_openframe'])

        await pg.evaluate("() => { openFrame('Collections'); }"); await asyncio.sleep(6)
        coll = next((f for f in pg.frames if 'Collections.aspx' in f.url), None)
        if coll:
            try:
                await coll.evaluate("""() => { const sel=document.querySelector('select[name="Terminals"]');
                    if(sel) for(let o of sel.options) o.selected = o.text.trim()==='Comet'; }""")
                await coll.click('text=Run Collections')
            except Exception as e: print("run click:", e)
            await asyncio.sleep(7)
            for frame in pg.frames:
                if 'Collections' in frame.url:
                    try:
                        rows = await frame.evaluate(r"""() => {
                            const trs=[...document.querySelectorAll('tr')]
                              .filter(r=>{const c=r.querySelectorAll('td');return c.length>=7 && c[1] && /^\d+$/.test(c[1].innerText.trim());});
                            return trs.slice(0,3).map(r=>r.outerHTML.slice(0,1200));
                        }""")
                        if rows: out['collections_row_html'] = rows; break
                    except: pass

        for target in ['AcctRec','AccountsReceivable','Aging','AgingReport','Invoices','ARReport','Receivables']:
            try:
                await pg.evaluate(f"() => {{ try{{ openFrame('{target}'); }}catch(e){{}} }}"); await asyncio.sleep(4)
                fr = next((f for f in pg.frames if target.lower()[:6] in f.url.lower()), None)
                if fr:
                    heads = await fr.evaluate(r"""() => {
                        const t=[...document.querySelectorAll('table')].map(tb=>{
                          const th=[...tb.querySelectorAll('th,tr:first-child td')].map(x=>x.innerText.trim()).filter(Boolean).slice(0,15);
                          return th.join(' | ');
                        }).filter(x=>x.length>5);
                        return {url: location.href, tables: t.slice(0,6)};
                    }""")
                    out['acctrec'][target] = heads
                    print(f"[{target}] reachable:", heads.get('url','')[:90])
            except Exception as e:
                pass

        out['frames'] = [f.url for f in pg.frames]
        out['json_endpoints'] = [u for u,b in resp.items() if b.strip()[:1] in '[{' and 'html' not in b[:50].lower()]
        out['post_endpoints'] = list(reqs.keys())
        await br.close()

    (OUT/'acctrec_probe.json').write_text(json.dumps({'summary': out, 'responses_sample': {k:v[:600] for k,v in list(resp.items())[:40]}}, indent=2))
    print("\n=== SUMMARY ===")
    print("menu:", out['menu_openframe'])
    print("AR screens reachable:", list(out['acctrec'].keys()))
    for t,d in out['acctrec'].items():
        for tab in d.get('tables',[]): print(f"  [{t}] TABLE:", tab)
    print("JSON endpoints seen:", [u.split('goctl.com')[-1][:70] for u in out['json_endpoints']][:15])
    print("first Collections row html[:400]:", (out['collections_row_html'][0][:400] if out['collections_row_html'] else 'none'))
    print("wrote /opt/xcelerator/output/acctrec_probe.json")

asyncio.run(run())
