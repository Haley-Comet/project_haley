# comet-ops
VPS scripts for Comet Messenger Service Haley 2.0 stack.

## Scripts
- scraper.py — Live dispatch dashboard scraper (every 10min)
- order_scraper.py — Full order scraper to Supabase Orders (every 15min)  
- ar_scraper.py — AR collections scraper (weekday mornings)
- supabase_backup.py — Nightly full Supabase backup (2am)
- watchdog.sh — Container health watchdog (every 10min)

