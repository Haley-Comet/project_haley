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
    acct = ''.join(filter(str.isdigit, o.get('AccountNo','') or '')) or None
    return {
        'ordertrackingid': o.get('OrderTrackingID'),
        'accountno':       i(acct),
        'company_name':    o.get('CompanyName'),
        'status':          o.get('Status'),
        'service':         o.get('Service'),
        'order_charge':    n(o.get('OrderCharge')),
        'grand_total':     n(o.get('GrandTotal')),
        'driver_no':       o.get('DriverNo'),
        'mileage':         n(o.get('MileageTotal')),
        'pieces':          i(o.get('SPieces')),
        'weight':          n(o.get('SWeight')),
        'pickup_company':  o.get('PCoName'),
        'pickup_contact':  o.get('PContact'),
        'pickup_phone':    o.get('PPhone'),
        'pickup_street':   o.get('PStreet'),
        'pickup_city':     o.get('PCity'),
        'pickup_state':    o.get('PState'),
        'pickup_zip':      o.get('PZip'),
        'delivery_company':o.get('DCoName'),
        'delivery_contact':o.get('DContact'),
        'delivery_phone':  o.get('DPhone'),
        'delivery_street': o.get('DStreet'),
        'delivery_city':   o.get('DCity'),
        'delivery_state':  o.get('DState'),
        'delivery_zip':    o.get('DZip'),
        'pod_name':        o.get('PODName'),
        'caller':          o.get('Caller'),
        'csr':             o.get('CSR'),
        'ref':             o.get('ClientRefNo'),
        'ref_2':           o.get('ClientRefNo2'),
    }

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now()
    today = now.strftime('%m/%d/%Y')
    print(f"[{now.strftime('%H:%M:%S')}] Comet Order Scraper...")

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
                "PickupTargetToDateStart": today, "PickupTargetToDateEnd": "null",
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

            # Use absolute URL — avoids relative path resolution issues
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
        terminals = {}
        for o in all_orders:
            t = o.get('TerminalName', '?')
            terminals[t] = terminals.get(t, 0) + 1
        print(f"    Terminals: {terminals}")

        if all_orders:
            rows = [map_order(o) for o in all_orders if o.get('OrderTrackingID')]
            print(f"    Upserting {len(rows)} rows...")
            for i in range(0, len(rows), 50):
                chunk = rows[i:i+50]
                r = requests.post(f'{SUPA}/rest/v1/Orders', headers=HDRS, json=chunk)
                print(f"    Chunk {i//50+1}: {r.status_code}")
                if r.status_code >= 400:
                    print(f"    Error: {r.text[:200]}")

        (OUT/'order_scraper_last.json').write_text(json.dumps(all_orders[:3], indent=2))
        await br.close()
        print("    Done ✓")

asyncio.run(run())
