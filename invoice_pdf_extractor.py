#!/usr/bin/env python3
import requests, re, io, time
import pdfplumber

SUPA = "https://ykuzxqmshzoywvufynps.supabase.co"
KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlrdXp4cW1zaHpveXd2dWZ5bnBzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTYzNTg2MCwiZXhwIjoyMDg3MjExODYwfQ.iPmB6TengyGSKMOk-4ZVK6a06Vz3lC01veM8ISZVmRY"
HEADS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def parse_pdf(pdf_bytes):
    result = {"amount": None, "company_name": None}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        m = re.search(r'Amount Due\s*\$?([\d,]+\.?\d*)', text, re.I)
        if m:
            result["amount"] = float(m.group(1).replace(',', ''))
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if 'Remit Payments to' in line:
                for j in range(max(0, i-5), i):
                    c = lines[j]
                    if (c and not re.match(r'^\d', c) and
                        not re.search(r'(Chicago|IL|ph:|www\.|cut and|Invoice|Acct|Payment|\*)', c, re.I) and
                        len(c) > 3 and '$' not in c):
                        result["company_name"] = c
                        break
                break
    except Exception as e:
        print(f"  parse error: {e}")
    return result

def run():
    url = f"{SUPA}/rest/v1/invoices?select=invoice_number,account_number,pdf_url,amount&limit=200"
    r = requests.get(url, headers=HEADS)
    invoices = r.json()
    if not isinstance(invoices, list):
        print(f"Error fetching invoices: {invoices}")
        return

    no_amount = [i for i in invoices if i.get('amount') is None and i.get('pdf_url')]
    print(f"Total: {len(invoices)} | Missing amount: {len(no_amount)}")

    updated = failed = 0
    for inv in no_amount:
        inv_num = inv['invoice_number']
        try:
            resp = requests.get(inv['pdf_url'], timeout=15)
            if resp.status_code != 200:
                print(f"  {inv_num}: HTTP {resp.status_code}")
                failed += 1
                continue

            parsed = parse_pdf(resp.content)
            if parsed['amount'] is None:
                print(f"  {inv_num}: no amount found")
                failed += 1
                continue

            update = {"amount": parsed['amount']}
            if parsed['company_name']:
                update["company_name"] = parsed['company_name']

            patch = requests.patch(
                f"{SUPA}/rest/v1/invoices?invoice_number=eq.{inv_num}",
                headers={**HEADS, "Prefer": "return=minimal"},
                json=update
            )
            if patch.status_code in (200, 204):
                co = parsed['company_name'] or ''
                print(f"  {inv_num}: ${parsed['amount']:.2f}" + (f" | {co}" if co else ""))
                updated += 1
            else:
                print(f"  {inv_num}: patch {patch.status_code}")
                failed += 1
        except Exception as e:
            print(f"  {inv_num}: {e}")
            failed += 1
        time.sleep(0.1)

    print(f"\nDone: {updated} updated, {failed} failed")

run()
