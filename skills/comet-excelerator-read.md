# Excelerator (Xcelerator/CTL) Read-Navigation

*Taught 2026-08-15. Part A verified against the database; Part B extracted from the production scraper /opt/xcelerator/scripts/order_scraper.py and a live portal session that day. **READ-ONLY skill: never create, edit, or delete anything in Excelerator.***

## Part A - What the data means (the "Orders" view, 75 columns)

These are exactly the fields Excelerator provides, as landed in Supabase by the 15-minute scraper cron:

- **Identity/refs:** ordertrackingid (unique key), ref, ref_2, ref_3, ref_4, round_trip, invoice_batch
- **Account:** accountno, company_name, caller, csr
- **Pickup:** pickup_company/contact/phone/street/street2/city/state/zip, pickup_special_instr, pickup_window_start/end, pickup_arrival/departure
- **Delivery:** delivery_* (same set), delivery_special_instr, delivery_window_start/end, delivery_arrival/departure
- **Package/service:** packages, pieces, weight, vehicle, service
- **Money:** order_charge, grand_total, mileage, svalue, cod, driver_pay, payment_status
- **Lifecycle/status:** status, outcome, scheduling_status, order_created_at, order_date, updated_at, delivered_at, cancelled_at, cancel_reason
- **Proof of delivery:** pod_name/date/time, pod_completion, rt_pod_name/date/time, signature_raw/clean/type/valid, photo_url
- **Driver/route:** route_no, driver_no, driver_pay

Status codes are defined in comet-order-doctrine.md - apply that doctrine to any Excelerator-derived data too.

## Part B - How to reach the data (portal navigation)

- **Login:** https://www.goctl.com/Main/home. Form fields input[name="UserName"], input[name="Password"], then button[type="submit"]. Credentials come from the runtime secret store (GOCTL_USER / GOCTL_PASS) - **never written in a skill, message, or log.**
- **The portal is a frameset SPA.** The top menu bar (Accounting, Administration, Distribution, Operations, Reports, TariffBuilder, Utilities, Warehousing) loads sections into named iframes (DashboardFrame, AcctRecFrame, CollectionsFrame, ReviewOrdFrame, StandardRepFrame, ...). A global JS helper switches sections: e.g. openFrame('ReviewOrd') opens Review Orders. After opening, the working document is the *inner* iframe whose URL contains reviewOrdersSubFrame.
- **Order data endpoint (read):** inside that frame, orders come from POST /api/revieworders/GetReviewOrders (JSON). Useful filter fields observed in production: Status "A" (= all), OrderTrackingID, AccountNo, DriverNo, ClientRefNo, RouteNo, CSR, DateField "CreationUtc" with date-range fields, and paging via take/skip/page/pageSize (100/page). The response JSON uses PascalCase keys (OrderTrackingID, OrderCharge, GrandTotal, SUMDrvComm, MileageTotal, SPieces, SWeight, Caller, CSR, ClientRefNo...), which the scraper maps to the snake_case columns in Part A.
- **Useful UI paths seen live:** Accounting > Collections (collections session screen); Accounting > Accounts Rec.; Reports > Standard Reports > Accounting folder (Aged Trial Balance, Accounts Receivable Summary, etc. - reports render in-page with Export / Print PDF buttons).

## Hard rules

- Reads only. Do not touch Order Entry, submitorder, batch posting, or anything that changes state. Order creation (Retell - Order to Excelerator) is deliberately OFF and out of scope.
- Prefer the Supabase copy (the "Orders" view) for questions it can answer - same data, no login. Go to the portal only for what is not scraped (e.g. live report screens).
