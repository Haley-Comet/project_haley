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
        # Return ISO timestamp string or None
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
        # Identity
        'ordertrackingid':      o.get('OrderTrackingID'),
        'accountno':            i(acct),
        'company_name':         o.get('CompanyName'),
        'order_date':           tz(o.get('ODate')),
        'order_created_at':     t(o.get('CreationUtc')),
        # Status & service
        'status':               o.get('Status'),
        'scheduling_status':    o.get('SchedulingStatus'),
        'invoice_batch':      (str(o.get('InvBatchID')) if o.get('InvBatchID') not in (None, 0, '0', '') else None),
        'service':              o.get('Service'),
        'vehicle':              o.get('Vehicle'),
        'round_trip':           o.get('RoundTrip'),
        'route_no':             o.get('RouteNo') or None,
        # Financials
        'order_charge':         n(o.get('OrderCharge')),
        'grand_total':          n(o.get('GrandTotal')),
        'driver_pay':           n(o.get('SUMDrvComm')),
        'svalue':               n(o.get('SValue')),
        'cod':                  n(o.get('COD')),
        # Driver
        'driver_no':            i(o.get('DriverNo')),
        # Shipment
        'mileage':              n(o.get('MileageTotal')),
        'pieces':               i(o.get('SPieces')),
        'weight':               n(o.get('SWeight')),
        # Caller
        'caller':               o.get('Caller'),
        'email':                o.get('Email') or None,
        'csr':                  o.get('CSR'),
        'ref':                  o.get('ClientRefNo'),
        'ref_2':                o.get('ClientRefNo2'),
        'ref_3': o.get('ClientRefNo3'),
        'ref_4': o.get('ClientRefNo4'),
        # Pickup address
        'pickup_company':       o.get('PCoName'),
        'pickup_contact':       o.get('PContact'),
        'pickup_phone':         o.get('PPhone'),
        'pickup_street':        o.get('PStreet'),
        'pickup_street2':       o.get('PStreet2') or None,
        'pickup_city':          o.get('PCity'),
        'pickup_state':         o.get('PState'),
        'pickup_zip':           o.get('PZip'),
        # Delivery address
        'delivery_company':     o.get('DCoName'),
        'delivery_contact':     o.get('DContact'),
        'delivery_phone':       o.get('DPhone'),
        'delivery_street':      o.get('DStreet'),
        'delivery_street2':     o.get('DStreet2') or None,
        'delivery_city':        o.get('DCity'),
        'delivery_state':       o.get('DState'),
        'delivery_zip':         o.get('DZip'),
        # Time windows
        'pickup_window_start':  t(o.get('PickupTargetFrom')),
        'pickup_window_end':    t(o.get('PickupTargetTo')),
        'delivery_window_start':t(o.get('DeliveryTargetFrom')),
        'delivery_window_end':  t(o.get('DeliveryTargetTo')),
        # Delivery stage timestamps
        'pickup_arrival':       tz(o.get('PickupArrival')),
        'pickup_departure':     tz(o.get('PickupDeparture')),
        'delivery_arrival':     tz(o.get('DeliveryArrival')),
        'delivery_departure':   tz(o.get('DeliveryDeparture')),
        # POD
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

    # Billing period starts last Sunday (Mon=0 ... Sun=6)
    days_since_sunday = (now.weekday() + 1) % 7
    billing_start = now - timedelta(days=days_since_sunday)
    billing_start_str = billing_start.strftime('%m/%d/%Y')

    print(f"[{now.strftime('%H:%M:%S')}] Comet Order Scraper...")
    print(f"    Date range: {billing_start_str} → {today}")

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
                "PickupTargetToDateStart": billing_start_str, "PickupTargetToDateEnd": "null",
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
                r = requests.post(f'{SUPA}/rest/v1/orders', headers=HDRS, json=chunk)
                print(f"    Chunk {i//50+1}: {r.status_code}")
                if r.status_code >= 400:
                    print(f"    Error: {r.text[:200]}")

        (OUT/'order_scraper_last.json').write_text(json.dumps(all_orders[:3], indent=2))

        # Heartbeat: order ingest completed -- fires every run; 0 orders is a valid, healthy value
        hb0 = {'scraper_name': 'order_scraper',
               'last_success': datetime.utcnow().isoformat() + 'Z',
               'last_error': None,
               'order_count': len(all_orders)}
        requests.post(f'{SUPA}/rest/v1/scraper_heartbeats', headers=HDRS, json=[hb0])
        print('    Order scraper heartbeat updated')

        # ── DELETED SWEEP (P16, 2026-08-10) ─────────────────
        # Pull the board's real Status=Deleted list for the same billing window
        # and stamp orders.deleted_at via the apply_deleted_orders RPC.
        # The *Active id list is passed too so an order un-deleted on the board
        # gets its deleted_at cleared. Read-only against the board; rows are
        # kept in Supabase as history (never hard-deleted here).
        try:
            deleted_orders = []
            dpage = 1
            while True:
                dbody = {
                    "Terminals": "22",
                    "DCSegments": "0", "ServiceTypes": "0", "VehicleTypes": "0",
                    "Origination": "A", "Status": "D", "OrderTypes": "A",
                    "SchedulingStatus": "A", "SchedulingSubStatuses": "0",
                    "ProposalStatuses": "0", "PackageTypes": "0", "SpecialAttributes": "0",
                    "OrderTrackingID": "", "AccountNo": "", "DriverNo": "",
                    "ClientRefNo": "", "ClientRefNo2": "", "RouteNo": "", "CSR": "",
                    "DateField": "CreationUtc",
                    "CreationUtcFrom": "null", "CreationUtcTo": "null",
                    "PickupTargetToDateStart": billing_start_str, "PickupTargetToDateEnd": "null",
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
                    "take": 100, "skip": (dpage - 1) * 100,
                    "page": dpage, "pageSize": 100, "sort": []
                }
                dresult = await sub.evaluate("""async (b) => {
                    const r = await fetch('/api/revieworders/GetReviewOrders', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(b)
                    });
                    return {status: r.status, body: await r.text()};
                }""", dbody)
                if dresult['status'] != 200:
                    print(f"    Deleted sweep: page {dpage} HTTP {dresult['status']} — aborting sweep")
                    deleted_orders = None
                    break
                dbatch = json.loads(dresult['body']).get('Data', [])
                deleted_orders.extend(dbatch)
                if len(dbatch) < 100:
                    break
                dpage += 1

            if deleted_orders is not None:
                deleted_ids = sorted({o.get('OrderTrackingID') for o in deleted_orders if o.get('OrderTrackingID')})
                active_ids  = sorted({o.get('OrderTrackingID') for o in all_orders   if o.get('OrderTrackingID')})
                print(f"    Deleted sweep: {len(deleted_ids)} deleted on board (window from {billing_start_str})")
                r = requests.post(f'{SUPA}/rest/v1/rpc/apply_deleted_orders', headers=HDRS,
                                  json={'p_deleted_ids': deleted_ids, 'p_active_ids': active_ids})
                print(f"    Deleted sweep RPC: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"    Deleted sweep error (non-fatal): {e}")
        # ── END DELETED SWEEP ───────────────────────────────

        # ── DRIVER POSITIONS + ORDER TRACKING ───────────────
        print("\n    ── Live Tracking Data ──")
        try:
            # Fetch driver GPS positions using the existing browser session
            drv_result = await pg.evaluate("""async () => {
                const r = await fetch('/api/dispatchmaps/driverpositions?_p_Terminals=22,23&_p_DCSegments=0&_p_Vehicles=0&_p_Services=0&_p_TimeSpan=0&_p_MarkedOrders=0&_p_SchedStatuses=0&_p_OrderTypes=0&_p_Accounts=&_p_SourceOfBizCodes=&_p_OrderSpecialAttributeIds=&_p_OrderSpecialAttributeFilterType=ANY&_p_DriverNos=&_p_SpecialAttributeIds=&_p_SpecialAttributeFilterType=ANY&_p_ApplyOrderFilters=0', {
                    method: 'POST'
                });
                return {status: r.status, body: await r.text()};
            }""")

            if drv_result['status'] == 200:
                drv_data = json.loads(drv_result['body'])
                drivers = drv_data.get('Data', drv_data) if isinstance(drv_data, dict) else drv_data
                print(f"    Drivers: {len(drivers)} positions")

                # Transform and upsert driver locations
                drv_now = datetime.utcnow().isoformat() + 'Z'
                drv_rows = []
                for d in drivers:
                    drv_rows.append({
                        'driver_id':     d['DriverID'],
                        'driver_no':     d['DriverNo'],
                        'driver_name':   d['DriverName'],
                        'vehicle':       d.get('Vehicle', ''),
                        'latitude':      d.get('Latitude'),
                        'longitude':     d.get('Longitude'),
                        'speed':         d.get('Speed', 0),
                        'minutes_since': d.get('MinutesSince', 0),
                        'order_count':   d.get('OrderCount', 0),
                        'package_count': d.get('PackageCount', 0),
                        'late_warning':  d.get('LateWarning', 0),
                        'updated_at':    drv_now,
                    })

                if drv_rows:
                    r = requests.post(f'{SUPA}/rest/v1/driver_locations', headers=HDRS, json=drv_rows)
                    print(f"    Driver upsert: {r.status_code} ({len(drv_rows)} rows)")
                    if r.status_code >= 400:
                        print(f"    Error: {r.text[:200]}")
            else:
                print(f"    Driver fetch failed: {drv_result['status']}")

            # Fetch order positions (pickup/delivery coords + driver assignment)
            ord_result = await pg.evaluate("""async () => {
                const r = await fetch('/api/dispatchmaps/orderpositions?_p_terminals=22,23&_p_dcSegments=0&_p_vehicles=0&_p_services=0&_p_timeSpan=0&_p_markedOrders=0&_p_pickup=1&_p_delivery=1&_p_assignment=0&_p_drivers=&_p_IsTablet=false&_p_SchedStatuses=0&_p_orderTypes=0&_p_accounts=&_p_SourceOfBizCodes=&_p_SpecialAttributeIds=&_p_SpecialAttributeFilterType=ANY', {
                    method: 'POST'
                });
                return {status: r.status, body: await r.text()};
            }""")

            if ord_result['status'] == 200:
                ord_data = json.loads(ord_result['body'])
                orders_live = ord_data.get('Data', ord_data) if isinstance(ord_data, dict) else ord_data
                print(f"    Orders:  {len(orders_live)} positions")

                # Transform and upsert order tracking
                def parse_dt(v):
                    """Parse Xcelerator datetime to ISO or None."""
                    if not v or not v.strip():
                        return None
                    try:
                        return datetime.strptime(v.strip(), '%m/%d/%Y %H:%M').replace(tzinfo=XCL_TZ).astimezone(timezone.utc).isoformat()
                    except ValueError:
                        try:
                            return datetime.strptime(v.strip(), '%m/%d/%Y %H:%M:%S').replace(tzinfo=XCL_TZ).astimezone(timezone.utc).isoformat()
                        except ValueError:
                            return None

                ord_rows = []
                # P17 2026-08-10: order_tracking.driver_id FKs driver_locations(driver_id).
                # With _p_assignment=0 (all orders) some drivers (e.g. dummy/billing) have
                # no GPS row this cycle — null driver_id for those, keep driver_no/name.
                known_driver_ids = {d.get('DriverID') for d in (drivers if 'drivers' in dir() else [])}
                for o in orders_live:
                    did = o.get('DriverID')
                    if did == 0:
                        did = None
                    if did is not None and did not in known_driver_ids:
                        did = None
                    ord_rows.append({
                        'order_tracking_id':    o['OrderTrackingId'],
                        'account_no':           o['AccountNo'],
                        'company_name':         o.get('CompanyName', ''),
                        'pickup_latitude':      o.get('PickupLatitude'),
                        'pickup_longitude':     o.get('PickupLongitude'),
                        'pickup_company':       o.get('PCoName', ''),
                        'pickup_street':        o.get('PStreet', ''),
                        'pickup_street2':       o.get('PStreet2', ''),
                        'pickup_city':          o.get('PCity', ''),
                        'pickup_state':         o.get('PState', ''),
                        'pickup_zip':           o.get('PZip', ''),
                        'delivery_latitude':    o.get('DeliveryLatitude'),
                        'delivery_longitude':   o.get('DeliveryLongitude'),
                        'delivery_company':     o.get('DCoName', ''),
                        'delivery_street':      o.get('DStreet', ''),
                        'delivery_street2':     o.get('DStreet2', ''),
                        'delivery_city':        o.get('DCity', ''),
                        'delivery_state':       o.get('DState', ''),
                        'delivery_zip':         o.get('DZip', ''),
                        'pickup_target_from':   parse_dt(o.get('PickupTargetFrom', '')),
                        'pickup_target_to':     parse_dt(o.get('PickupTargetTo', '')),
                        'delivery_target_from': parse_dt(o.get('DeliveryTargetFrom', '')),
                        'delivery_target_to':   parse_dt(o.get('DeliveryTargetTo', '')),
                        'pickup_arrival':       parse_dt(o.get('PickupArrival', '')),
                        'pickup_departure':     parse_dt(o.get('PickupDeparture', '')),
                        'pickup_complete':      o.get('PickupComplete', False),
                        'driver_id':            did,
                        'driver_no':            o.get('DriverNo') or None,
                        'driver_name':          o.get('DriverName', ''),
                        'service':              o.get('Service', ''),
                        'vehicle':              o.get('Vehicle', ''),
                        'order_type':           o.get('OrderType', ''),
                        'scheduling_status':    o.get('SchedulingStatus', ''),
                        'pieces':               o.get('Pieces', 0),
                        'weight':               o.get('sWeight', 0),
                        'updated_at':           drv_now,
                    })

                if ord_rows:
                    r = requests.post(f'{SUPA}/rest/v1/order_tracking', headers=HDRS, json=ord_rows)
                    print(f"    Order tracking upsert: {r.status_code} ({len(ord_rows)} rows)")
                    if r.status_code >= 400:
                        print(f"    Error: {r.text[:200]}")
            else:
                print(f"    Order positions fetch failed: {ord_result['status']}")

            # Update heartbeat
            hb = {'scraper_name': 'driver_scraper', 'last_success': drv_now,
                   'driver_count': len(drv_rows) if 'drv_rows' in dir() else 0,
                   'order_count': len(ord_rows) if 'ord_rows' in dir() else 0}
            requests.post(f'{SUPA}/rest/v1/scraper_heartbeats', headers=HDRS, json=[hb])
            print("    Heartbeat updated ✓")

        except Exception as e:
            print(f"    Live tracking error (non-fatal): {e}")
        # ── END DRIVER POSITIONS BLOCK ──────────────────────
        await br.close()
        print("    Done ✓")

asyncio.run(run())
