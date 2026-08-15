import asyncio, os, json, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
XCL_TZ = ZoneInfo("America/Chicago")


for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

USER = os.environ['GOCTL_USER']
PASS = os.environ['GOCTL_PASS']
SUPA = os.environ['SUPABASE_URL']
KEY  = os.environ['SUPABASE_KEY']
OUT  = Path('/opt/xcelerator/output')
HDRS = {'apikey': KEY, 'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates,return=minimal'}

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=50)
    await pg.type('input[name="Password"]', PASS, delay=50)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load')
    await asyncio.sleep(6)

def map_order(o):
    def n(v):
        try: return float(v) if v else None
        except: return None
    def i(v):
        try: return int(str(v).replace(',','').split('.')[0]) if v else None
        except: return None
    def t(v):
        return v if v else None
    def tz(v):
        # Xcelerator sends naive LOCAL wall clock (America/Chicago).
        # Attach the real zone and convert to true UTC; DST resolved per value.
        if not v:
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).isoformat()
        return dt.replace(tzinfo=XCL_TZ).astimezone(timezone.utc).isoformat()
    acct = ''.join(filter(str.isdigit, o.get('AccountNo','') or '')) or None
    return {
        'ordertrackingid':      o.get('OrderTrackingID'),
        'accountno':            i(acct),
        'company_name':         o.get('CompanyName'),
        'order_date':           tz(o.get('ODate')),
        'order_created_at':     t(o.get('CreationUtc')),
        'status':               o.get('Status'),
        'scheduling_status':    o.get('SchedulingStatus'),
        'invoice_batch':      (str(o.get('InvBatchID')) if o.get('InvBatchID') not in (None, 0, '0', '') else None),
        'service':              o.get('Service'),
        'vehicle':              o.get('Vehicle'),
        'round_trip':           o.get('RoundTrip'),
        'route_no':             o.get('RouteNo') or None,
        'order_charge':         n(o.get('OrderCharge')),
        'grand_total':          n(o.get('GrandTotal')),
        'driver_pay':           n(o.get('SUMDrvComm')),
        'svalue':               n(o.get('SValue')),
        'cod':                  n(o.get('COD')),
        'driver_no':            i(o.get('DriverNo')),
        'mileage':              n(o.get('MileageTotal')),
        'pieces':               i(o.get('SPieces')),
        'weight':               n(o.get('SWeight')),
        'caller':               o.get('Caller'),
        'email':                o.get('Email') or None,
        'csr':                  o.get('CSR'),
        'ref':                  o.get('ClientRefNo'),
        'ref_2':                o.get('ClientRefNo2'),
        'ref_3': o.get('ClientRefNo3'),
        'ref_4': o.get('ClientRefNo4'),
        'pickup_company':       o.get('PCoName'),
        'pickup_contact':       o.get('PContact'),
        'pickup_phone':         o.get('PPhone'),
        'pickup_street':        o.get('PStreet'),
        'pickup_street2':       o.get('PStreet2') or None,
        'pickup_city':          o.get('PCity'),
        'pickup_state':         o.get('PState'),
        'pickup_zip':           o.get('PZip'),
        'delivery_company':     o.get('DCoName'),
        'delivery_contact':     o.get('DContact'),
        'delivery_phone':       o.get('DPhone'),
        'delivery_street':      o.get('DStreet'),
        'delivery_street2':     o.get('DStreet2') or None,
        'delivery_city':        o.get('DCity'),
        'delivery_state':       o.get('DState'),
        'delivery_zip':         o.get('DZip'),
        'pickup_window_start':  t(o.get('PickupTargetFrom')),
        'pickup_window_end':    t(o.get('PickupTargetTo')),
        'delivery_window_start':t(o.get('DeliveryTargetFrom')),
        'delivery_window_end':  t(o.get('DeliveryTargetTo')),
        'pickup_arrival':       tz(o.get('PickupArrival')),
        'pickup_departure':     tz(o.get('PickupDeparture')),
        'delivery_arrival':     tz(o.get('DeliveryArrival')),
        'delivery_departure':   tz(o.get('DeliveryDeparture')),
        'pod_name':             o.get('PODName') or None,
        'pod_completion':       tz(o.get('PODcompletion')),
        'pod_date':             o.get('PODcompletionDate') or None,
        'pod_time':             o.get('PODcompletionTime') or None,
        'rt_pod_name':      o.get('PODNameRT') or None,
        'rt_pod_date':      o.get('POD_RTcompletionDate') or None,
        'rt_pod_time':      o.get('POD_RTcompletionTime') or None,
    }

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now()
    today = now.strftime('%m/%d/%Y')
    lookback = now - timedelta(weeks=6)
    lookback_str = lookback.strftime('%m/%d/%Y')

    print(f"[{now.strftime('%H:%M:%S')}] Comet Order Backfill Scraper (6-week)")
    print(f"    Date range: {lookback_str} → {today}")

    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900})
        pg.set_default_timeout(30000)

        print("    Logging in...")
        await login(pg)

        print("    Opening Review Orders frame...")
        await pg.evaluate("() => { openFrame('ReviewOrd'); }")
        await asyncio.sleep(10)

        sub = next((f for f in pg.frames if 'reviewOrdersSubFrame' in f.url), None)

        for _att in range(11):

            if sub: break

            if _att % 3 == 2:

                try: await pg.evaluate("() => { openFrame('ReviewOrd'); }")

                except Exception as _e: print(f'    openFrame retry err: {_e}')

            await asyncio.sleep(5)

            sub = next((f for f in pg.frames if 'reviewOrdersSubFrame' in f.url), None)
        if not sub:
            print("    ERROR: subframe not found")
            await br.close()
            return
        print(f"    Subframe found")

        all_orders = []
        page_num = 1

        while True:
            body = {
                "Terminals": "22",
                "DCSegments": "0", "ServiceTypes": "0", "VehicleTypes": "0",
                "Origination": "A", "Status": "A", "OrderTypes": "A",
                "SchedulingStatus": "A", "SchedulingSubStatuses": "0",
                "ProposalStatuses": "0", "PackageTypes": "0", "SpecialAttributes": "0",
                "OrderTrackingID": "", "AccountNo": "", "DriverNo": "",
                "ClientRefNo": "", "ClientRefNo2": "", "RouteNo": "", "CSR": "",
                "DateField": "CreationUtc",
                "CreationUtcFrom": "null", "CreationUtcTo": "null",
                "PickupTargetToDateStart": lookback_str, "PickupTargetToDateEnd": "null",
                "DeliveryTargetToDateStart": "null", "DeliveryTargetToDateEnd": "null",
                "PODcompletionDateStart": "null", "PODcompletionDateEnd": "null",
                "WildCardField1": "-1", "WildCardComparer1": "", "WildCardValue1": "",
                "WildCardField2": "-1", "WildCardComparer2": "", "WildCardValue2": "",
                "GroupByRouteNo": "0", "IsForEmail": "0",
                "FieldChooserStr": "", "FriendyFieldNameStr": "", "OrderIDs": "",
                "EmailFrom": "jamessailer@gmail.com", "EmailTo": "",
                "EmailSubject": "", "EmailComments": "NA",
                "BulkExport": "0", "LoadedProfileId": 0, "ExportAllPages": "0",
                "TimezoneAbbrev": "UTC", "MasterContractorId": None,
                "IncludeMasterContractorOrders": False,
                "take": 100, "skip": (page_num - 1) * 100,
                "page": page_num, "pageSize": 100, "sort": []
            }

            result = await sub.evaluate("""async (b) => {
                const r = await fetch('/api/revieworders/GetReviewOrders', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(b)
                });
                return {status: r.status, body: await r.text()};
            }""", body)

            print(f"    Page {page_num}: status={result['status']}")
            if result['status'] != 200:
                print(f"    Error: {result['body'][:300]}")
                break

            data = json.loads(result['body'])
            batch = data.get('Data', [])
            all_orders.extend(batch)
            print(f"    Page {page_num}: {len(batch)} orders (total: {len(all_orders)})")
            if len(batch) < 100:
                break
            page_num += 1

        print(f"\n    Total: {len(all_orders)} orders")

        if all_orders:
            rows = [map_order(o) for o in all_orders if o.get('OrderTrackingID')]
            print(f"    Upserting {len(rows)} rows...")
            upserted = 0
            for i in range(0, len(rows), 50):
                chunk = rows[i:i+50]
                r = requests.post(f'{SUPA}/rest/v1/orders', headers=HDRS, json=chunk)
                print(f"    Chunk {i//50+1}: {r.status_code}")
                if r.status_code >= 400:
                    print(f"    Error: {r.text[:200]}")
                else:
                    upserted += len(chunk)
            print(f"    Upserted {upserted} rows total")

        (OUT/'order_backfill_last.json').write_text(json.dumps(all_orders[:3], indent=2))
        await br.close()
        print("    Done ✓")

asyncio.run(run())
