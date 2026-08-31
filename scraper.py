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
                    key = r.url.split('/api/')[1].split('?')[0].rstrip('/')
                    captured[key] = json.loads(b)
            except: pass

        pg.on('response', on_response)
        await login(pg)
        print(f"    Logged in, {len(captured)} APIs captured")

        t  = captured.get('dashboard/gettotals', {})
        d  = unwrap(captured.get('dashboardchart/getdispatchstatus', []))
        dr = unwrap(captured.get('dashboardchart/getdispatchburn', []))
        ov = captured.get('dashboardchart/ordersoverview', {})

        sm = {i['Field'].strip(): int(i.get('Count') or 0) for i in d}
        drivers = sorted(
            [{'driver': i['Field'].strip(), 'orders': int(i.get('Count') or 0)}
             for i in dr if i.get('Count') and int(i.get('Count') or 0) > 0],
            key=lambda x: -x['orders']
        )[:8]

        # -- Deep fix 2026-08-30: dashboard chart APIs changed shape / no longer
        # fire on home, so sm/dr gave 0s. Read the board directly from
        # dispatchmaps/orderpositions (same call order_scraper.py uses).
        # Fail-open: on any error keep the legacy chart-derived values.
        ORD_URL = '/api/dispatchmaps/orderpositions?_p_terminals=22,23&_p_dcSegments=0&_p_vehicles=0&_p_services=0&_p_timeSpan=0&_p_markedOrders=0&_p_pickup=1&_p_delivery=1&_p_assignment=0&_p_drivers=&_p_IsTablet=false&_p_SchedStatuses=0&_p_orderTypes=0&_p_accounts=&_p_SourceOfBizCodes=&_p_SpecialAttributeIds=&_p_SpecialAttributeFilterType=ANY'
        board = None
        try:
            _r = await pg.evaluate(
                "async (u) => { const r = await fetch(u, {method:'POST'});"
                " return {status:r.status, body: await r.text()}; }",
                ORD_URL)
            if _r['status'] == 200:
                _j = json.loads(_r['body'])
                _rows = _j.get('Data', _j) if isinstance(_j, dict) else _j
                if isinstance(_rows, list):
                    _asn = [x for x in _rows if x.get('DriverNo') or x.get('DriverID')]
                    board = {'open_orders': len(_rows), 'assigned': len(_asn),
                             'unassigned': len(_rows) - len(_asn)}
                    _cnt = {}
                    for x in _asn:
                        _n = (x.get('DriverName') or '').strip() or str(x.get('DriverNo'))
                        _cnt[_n] = _cnt.get(_n, 0) + 1
                    drivers = sorted([{'driver': k, 'orders': v} for k, v in _cnt.items()],
                                     key=lambda x: -x['orders'])[:8]
                    # unassigned_due: unassigned orders whose pickup window is
                    # imminent (<= now+30min Chicago) or past; future-scheduled
                    # orders are excluded so the watchdog does not false-alarm.
                    # Unparseable pickup time on an unassigned order counts as
                    # due (fail-closed).
                    from datetime import timedelta
                    try:
                        from zoneinfo import ZoneInfo
                        _tz = ZoneInfo('America/Chicago')
                        _nowc = datetime.now(_tz)
                        _due = 0
                        for x in _rows:
                            if x.get('DriverNo') or x.get('DriverID'):
                                continue
                            try:
                                _t = datetime.strptime((x.get('PickupTargetFrom') or '').strip(), '%m/%d/%Y %H:%M').replace(tzinfo=_tz)
                                if _t <= _nowc + timedelta(minutes=30):
                                    _due += 1
                            except Exception:
                                _due += 1
                        board['unassigned_due'] = _due
                    except Exception:
                        board['unassigned_due'] = board['unassigned']
        except Exception as _e:
            print(f"    board fetch failed: {_e}")
            board = None

        data = {
            'scraped_at':      now.isoformat(),
            'open_orders':     (board['open_orders'] if board is not None else t.get('TodayOpenOrders', 0)),
            'completed_today': t.get('OrdersCompletedToday', 0),
            'on_time_pct':     t.get('OnTime', 0),
            'unassigned':      (board['unassigned'] if board is not None else sm.get('Unassigned', 0)),
        'unassigned_due': (board or {}).get('unassigned_due', 0),
            'assigned':        (board['assigned'] if board is not None else sm.get('Assigned', 0)),
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
