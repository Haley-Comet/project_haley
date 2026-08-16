#!/usr/bin/env python3
# ar_healthcheck.py — dead-man + anomaly watchdog for the AR scraper.
# Runs weekdays ~07:30 (after the 07:02 ar_scraper_v2 run). Pings Discord if:
#   - ar_collections has NO rows for today  -> scraper didn't run / failed silently
#   - today's row count is well below the recent norm -> partial run (e.g. session cliff)
#   - today's total past_due collapsed vs the previous run -> the exact 2026-08-15 failure
# Healthy runs print OK and post nothing (so Discord stays quiet unless something's wrong).
# Config from /opt/xcelerator/.env: SUPABASE_URL, SUPABASE_KEY, DISCORD_WEBHOOK_HEALTH.
#   --selftest  post a clearly-labelled test message to confirm the Discord wiring, then exit.
import os, sys, requests, datetime
from pathlib import Path

for line in Path('/opt/xcelerator/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

SUPA = os.environ['SUPABASE_URL'].rstrip('/')
KEY  = os.environ['SUPABASE_KEY']
HOOK = os.environ.get('DISCORD_WEBHOOK_HEALTH', '')
HDRS = {'apikey': KEY, 'Authorization': f'Bearer {KEY}'}
MIN_ROWS = 40           # ~45 accounts; below this is a partial/failed run
COLLAPSE = 0.5          # alert if today's past_due < 50% of the previous run's

def notify(msg, emoji='⚠️'):
    print(msg)
    if HOOK:
        try:
            requests.post(HOOK, json={'content': f'{emoji} **AR health** — {msg}'}, timeout=15)
        except Exception as e:
            print(f'(discord post failed: {e})')

def q(params):
    r = requests.get(f'{SUPA}/rest/v1/ar_collections', headers=HDRS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    if '--selftest' in sys.argv:
        notify('self-test — Discord wiring is working. No action needed.', emoji='✅')
        return
    today = datetime.date.today().isoformat()
    dates = sorted({r['run_date'] for r in q({'select': 'run_date', 'order': 'run_date.desc', 'limit': '3000'})},
                   reverse=True)
    if not dates or dates[0] != today:
        notify(f"no ar_collections rows for {today} (latest run_date = {dates[0] if dates else 'none'}). "
               f"The AR scraper may not have run.")
        return
    tod  = q({'select': 'past_due_amount,total_owed', 'run_date': f'eq.{today}'})
    prev = dates[1] if len(dates) > 1 else None
    prow = q({'select': 'past_due_amount', 'run_date': f'eq.{prev}'}) if prev else []
    n, pn = len(tod), len(prow)
    pd  = round(sum(float(r.get('past_due_amount') or 0) for r in tod), 2)
    ppd = round(sum(float(r.get('past_due_amount') or 0) for r in prow), 2)
    problems = []
    if n < max(MIN_ROWS, int(pn * 0.8)):
        problems.append(f"only {n} accounts today (prev run had {pn}) — possible partial run")
    if ppd > 0 and pd < ppd * COLLAPSE:
        problems.append(f"total past_due collapsed to ${pd:,.2f} from ${ppd:,.2f} on {prev}")
    if problems:
        notify(f"{today}: " + "; ".join(problems))
    else:
        print(f"OK {today}: {n} accounts, past_due ${pd:,.2f} (prev {prev}: {pn} accts, ${ppd:,.2f})")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        notify(f"healthcheck itself errored: {type(e).__name__}: {e}")
        raise
