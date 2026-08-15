#!/usr/bin/env python3
# dispatch_map_scraper.py
# Cron: */5 7-19 * * 1-5

import asyncio, json, logging, os
from datetime import datetime, timezone
from pathlib import Path
import httpx
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/var/log/dispatch_map_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

for line in Path("/opt/xcelerator/.env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

USER         = os.environ["GOCTL_USER"]
PASS         = os.environ["GOCTL_PASS"]
SUPA_URL     = os.environ["SUPABASE_URL"]
SUPA_KEY     = os.environ["SUPABASE_KEY"]

BASE         = "https://www.goctl.com"
LOGIN_URL    = BASE + "/account/Account/Login"
MAP_URL      = BASE + "/Dispatch/Maps/DispatchMap?_p_DriverNo=0&_p_OrderTrackingId="
PARAMS       = ("_p_Terminals=23&_p_DCSegments=0&_p_Vehicles=0&_p_Services=0"
                "&_p_TimeSpan=0&_p_MarkedOrders=0&_p_SchedStatuses=0&_p_OrderTypes=0"
                "&_p_Accounts=&_p_SourceOfBizCodes=&_p_OrderSpecialAttributeIds="
                "&_p_OrderSpecialAttributeFilterType=ANY&_p_DriverNos="
                "&_p_SpecialAttributeIds=&_p_SpecialAttributeFilterType=ANY"
                "&_p_ApplyOrderFilters=0&_p_LimitAccessToClients=&_p_TimeZoneId=10")
DRIVERS_URL  = BASE + "/api/dispatchmaps/drivers?" + PARAMS
POSITIONS_URL= BASE + "/api/dispatchmaps/driverpositions?" + PARAMS
MAPPOINT_URL = BASE + "/api/dispatchmaps/mappoint?" + PARAMS

def upsert_memory(key, value):
    with httpx.Client() as client:
        r = client.post(
            SUPA_URL + "/rest/v1/haley_memory?on_conflict=caller_phone,key",
            headers={
                "apikey": SUPA_KEY,
                "Authorization": "Bearer " + SUPA_KEY,
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            json={
                "caller_phone": "SYSTEM",
                "category": "system",
                "key": key,
                "value": value,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        r.raise_for_status()
        log.info("Upserted " + key)

async def scrape():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()
        log.info("Logging in...")
        await page.goto(LOGIN_URL)
        await page.type("input[name=\"UserName\"]", USER, delay=50)
        await page.type("input[name=\"Password\"]", PASS, delay=50)
        await page.click("button[type=\"submit\"]")
        await page.wait_for_load_state("load")
        log.info("Loading dispatch map...")
        await page.goto(MAP_URL)
        await page.wait_for_load_state("load")

        async def fetch(url):
            try:
                return await page.evaluate(
                    "fetch('" + url + "', {credentials:'include'}).then(r=>r.json())"
                )
            except Exception as e:
                log.warning("fetch failed for " + url + ": " + str(e))
                return {}

        drivers_raw    = await fetch(DRIVERS_URL)
        positions_raw  = await fetch(POSITIONS_URL)
        await page.wait_for_timeout(2000)
        mappoint_raw   = await fetch(MAPPOINT_URL)
        await browser.close()

    drivers   = drivers_raw if isinstance(drivers_raw, list) else []
    positions = (positions_raw.get("Data") or []) if isinstance(positions_raw, dict) else []
    orders    = (mappoint_raw.get("Data") or [])   if isinstance(mappoint_raw, dict) else []
    pos_map   = {x["DriverNo"]: x for x in positions}

    active, late = [], []
    for d in drivers:
        dno = d["DriverNo"]
        if dno not in pos_map:
            continue
        pos  = pos_map[dno]
        name = (d.get("FirstName","") + " " + d.get("LastName","")).strip() or ("Driver [" + str(dno) + "]")
        active.append({
            "driver_no": dno, "name": name,
            "vehicle": d.get("Vehicle") or pos.get("Vehicle",""),
            "order_count": pos["OrderCount"], "speed_mph": pos["Speed"],
            "minutes_since": pos["MinutesSince"], "late_warning": pos["LateWarning"],
            "lat": pos["Latitude"], "lng": pos["Longitude"],
        })
        if pos["LateWarning"] > 0:
            late.append(name + " [" + str(dno) + "]")

    active.sort(key=lambda x: x["order_count"], reverse=True)
    now_str     = datetime.now().strftime("%I:%M %p")
    total_ord   = sum(x["order_count"] for x in active)
    loaded      = [x for x in active if x["order_count"] > 0]
    loaded_str  = ", ".join(x["name"].split()[0] + " [" + str(x["driver_no"]) + "] " + str(x["order_count"]) + " orders" for x in loaded[:8])
    moving      = [x for x in active if x["speed_mph"] > 5]
    late_str    = ("LATE WARNINGS: " + "; ".join(late)) if late else "No late warnings"
    today_str   = datetime.now().strftime("%m/%d/%Y")
    q_today     = [o for o in orders if o.get("PickupTargetFrom","").startswith(today_str) and o.get("DriverNo",0)==0]

    summary = ("[" + now_str + "] " + str(len(active)) + " drivers on road, " + str(total_ord) + " active orders. "
               + str(len(moving)) + " moving. Loaded: " + (loaded_str or "none") + ". "
               + late_str + ". Queue: " + str(len(q_today)) + " unassigned today, " + str(len(orders)) + " total scheduled.")

    log.info("Summary: " + summary)
    upsert_memory("live_drivers", summary)
    upsert_memory("live_drivers_json", json.dumps({
        "as_of": datetime.now(timezone.utc).isoformat(),
        "active_drivers": active,
        "unassigned_today": len(q_today),
        "queue_total": len(orders),
    }))
    log.info("Done.")

if __name__ == "__main__":
    asyncio.run(scrape())
