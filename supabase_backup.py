#!/usr/bin/env python3
import json, gzip, os, requests, time
from datetime import datetime
from pathlib import Path

SUPA_URL = "https://ykuzxqmshzoywvufynps.supabase.co"
SUPA_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlrdXp4cW1zaHpveXd2dWZ5bnBzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTYzNTg2MCwiZXhwIjoyMDg3MjExODYwfQ.iPmB6TengyGSKMOk-4ZVK6a06Vz3lC01veM8ISZVmRY"
BACKUP_DIR = Path("/opt/backups/supabase")
LOG_FILE   = Path("/opt/backups/logs/backup.log")

HEADERS = {
    "apikey": SUPA_KEY,
    "Authorization": f"Bearer {SUPA_KEY}",
}

TABLES = [
    "client_accounts",
    "Orders",
    "invoices",
    "ar_collections",
    "leads",
    "haley_memory",
    "account_addresses",
    "haley_calls",
    "pending_approvals",
]

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def backup_table(table):
    all_rows = []
    chunk = 1000
    offset = 0
    while True:
        url = f"{SUPA_URL}/rest/v1/{table}?select=*&limit={chunk}&offset={offset}"
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            log(f"  ERROR {table}: {r.status_code} {r.text[:100]}")
            return None
        rows = r.json()
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < chunk:
            break
        offset += chunk
        time.sleep(0.1)
    return all_rows

def run():
    date_str = datetime.now().strftime("%Y-%m-%d")
    backup = {}
    total_rows = 0

    log("=== Backup started ===")

    for table in TABLES:
        rows = backup_table(table)
        if rows is not None:
            backup[table] = rows
            total_rows += len(rows)
            log(f"  {table}: {len(rows)} rows")
        else:
            backup[table] = []

    filename = BACKUP_DIR / f"supabase_{date_str}.json.gz"
    with gzip.open(filename, "wt", encoding="utf-8") as f:
        json.dump(backup, f)

    size = os.path.getsize(filename)
    log(f"Saved: {filename} ({size/1024/1024:.1f} MB, {total_rows} total rows)")

    cutoff = time.time() - (30 * 86400)
    for f in BACKUP_DIR.glob("supabase_*.json.gz"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            log(f"Deleted old backup: {f.name}")

    log("=== Backup complete ===\n")

if __name__ == "__main__":
    run()
