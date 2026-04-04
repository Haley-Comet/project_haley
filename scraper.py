import asyncio, os, json, requests
from datetime import datetime
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL']
KEY  = os.environ['SUPABASE_KEY']

def unwrap(data):
    if isinstance(data, dict) and 'Data' in data:
        return data['Data'] or []
    return data if isinstance(data, list) else []

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(6)

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now()
    print(f"[{now.strftime('%H:%M:%S')}] Starting...")
    captured = {}

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(20000)

        async def on_response(r):
            if '/api/' not in r.url or 'goctl.com' not in r.url:
                return
            try:
                b = await r.text()
                if b.strip()[:1] in '[{':
                    key = r.url.split('/api/')[1].split('?')[0]
                    captured[key] = json.loads(b)
            except: pass

        pg.on('response', on_response)
        await login(pg)
        print(f"    Logged in, {len(captured)} APIs captured")

        t  = captured.get('dashboard/gettotals', {})
        d  = unwrap(captured.get('dashboardchart/getdispatchstatus', []))
        dr = unwrap(captured.get('dashboardchart/getdispatchcountperformance', []))
        ov = captured.get('dashboardchart/ordersoverview', {})

        sm = {i['Field'].strip(): int(i.get('Count') or 0) for i in d}
        drivers = sorted(
            [{'driver': i['Field'].strip(), 'orders': int(i.get('Count') or 0)}
             for i in dr if i.get('Count') and int(i.get('Count') or 0) > 0],
            key=lambda x: -x['orders']
        )[:8]

        data = {
            'scraped_at':      now.isoformat(),
            'open_orders':     t.get('TodayOpenOrders', 0),
            'completed_today': t.get('OrdersCompletedToday', 0),
            'on_time_pct':     t.get('OnTime', 0),
            'unassigned':      sm.get('Unassigned', 0),
            'assigned':        sm.get('Assigned', 0),
            'avg_per_hour':    ov.get('AverageRunsPerHour', 0) if isinstance(ov, dict) else 0,
            'drivers':         drivers,
        }
        flag = 'WARNING ' if data['unassigned'] > 0 else ''
        drv  = ', '.join(f"{d['driver']}({d['orders']})" for d in drivers)
        data['summary'] = (
            f"{flag}{data['open_orders']} orders active. "
            f"Assigned:{data['assigned']} Unassigned:{data['unassigned']} "
            f"Completed:{data['completed_today']} OnTime:{data['on_time_pct']:.0f}% "
            f"Drivers: {drv}"
        )
        print(f"\n>>> {data['summary']}")

        requests.post(
            f'{SUPA}/rest/v1/haley_memory',
            headers={'apikey': KEY, 'Authorization': f'Bearer {KEY}',
                     'Content-Type': 'application/json',
                     'Prefer': 'resolution=merge-duplicates,return=minimal'},
            json={'category': 'SYSTEM', 'key': 'excelerator_live',
                  'value': json.dumps(data), 'confidence': 5,
                  'active': True, 'source_call_id': 'scraper'}
        )
        Path('/opt/xcelerator/output/last_scrape.json').write_text(json.dumps(data, indent=2))
        await br.close()
        print("    Done ✓")

asyncio.run(run())
