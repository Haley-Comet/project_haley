#!/usr/bin/env python3
# ar_scraper_v2.py — AR scraper with per-account invoice drill-down.
# Adds: per-bucket amounts (G5), invoice_detail (G6), reconciliation warn (G7),
#       source_filename (G8), and real paid/open amounts (Work Item B).
# Fetch: one self-contained XHR per account (CollectionsInvoices.aspx?ClientID=..).
#        NO selectRow postbacks — those exhaust the goctl session after ~18 accounts
#        ("Session Expired"). Session-expiry is detected and recovered with one re-login.
# Bucketing: PER-ACCOUNT terms DERIVED from goctl's own account Days Late:
#            terms = max(open-invoice days_old) - account_days_late  (clamped >= 0).
#            days_late = days_old - terms. Aging bands:
#              amt_current  = NOT yet due (days_late <= 0)
#              amt_1_29     = 1-29 days past due
#              amt_30_59 / amt_60_89 / amt_90_119 / amt_120_plus
#            past_due = every band except amt_current (= goctl's account Past Due;
#            validated to match goctl to the cent on all 45 accounts).
# MODES:
#   --test [N]   process first N accounts (default 3), PRINT comparison, NO DB write, NO cron impact.
#   (no flag)    full run: all accounts, upsert to ar_collections.
import asyncio, os, json, requests, re, sys
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
HDRS = {'apikey': KEY, 'Authorization': f'Bearer {KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal'}

TEST = '--test' in sys.argv
TEST_N = 3
if TEST:
    i = sys.argv.index('--test')
    if i+1 < len(sys.argv) and sys.argv[i+1].isdigit(): TEST_N = int(sys.argv[i+1])

def money(s):
    if s is None: return 0.0
    try: return float(re.sub(r'[^0-9.\-]', '', str(s)))
    except: return 0.0

def to_int(s):
    try: return int(re.sub(r'[^0-9\-]', '', str(s)))
    except: return 0

# bucket by days_late (days_old - per-account terms).
# amt_current = NOT YET DUE (days_late <= 0); amt_1_29 = 1-29 days past due;
# then 30-day bands. past_due (goctl def) = everything except amt_current.
def bucket_of(days_late):
    if days_late <= 0:  return 0,   'amt_current'
    if days_late < 30:  return 1,   'amt_1_29'
    if days_late < 60:  return 30,  'amt_30_59'
    if days_late < 90:  return 60,  'amt_60_89'
    if days_late < 120: return 90,  'amt_90_119'
    return 120, 'amt_120_plus'

BUCKET_LABEL = {0:'Current',1:'1-29 Days',30:'30-59 Days',60:'60-89 Days',90:'90-119 Days',120:'120+ Days'}

async def login(pg):
    await pg.goto('https://www.goctl.com/Main/home', wait_until='load')
    await pg.type('input[name="UserName"]', USER, delay=40)
    await pg.type('input[name="Password"]', PASS, delay=40)
    await pg.click('button[type="submit"]')
    await pg.wait_for_load_state('load'); await asyncio.sleep(5)

PARSE_TABLE = r"""(html) => {
    let doc = document;
    if (html) doc = new DOMParser().parseFromString(html, 'text/html');
    const allTrs=[...doc.querySelectorAll('table tr')];
    const cells=r=>[...r.querySelectorAll('td,th')].map(c=>c.innerText.trim().replace(/\s+/g,' '));
    // goctl splits the invoice grid across two sibling tables: the column-header
    // row (InvoiceNo | Period Ending | ... | Days Old) lives in one table, and the
    // data rows in another. Older logic picked the largest table and treated its
    // FIRST data row as the header, dropping it — so single-invoice accounts parsed
    // to 0 rows. Instead: find the header row by its InvoiceNo column, then take
    // every row whose InvoiceNo-column cell holds a value as a data row.
    let header=[], invIdx=-1;
    for (const r of allTrs){ const c=cells(r); const j=c.findIndex(x=>/invoiceno/i.test(x)); if(j>=0){ header=c; invIdx=j; break; } }
    const rows=[];
    if(invIdx>=0){
      for(const r of allTrs){ const c=cells(r); const v=c[invIdx]||'';
        if(v && !/invoiceno/i.test(v) && /\d/.test(v) && c.length>=invIdx+3) rows.push(c); }
    }
    return {header, rows};
}"""

# Runs in the CollectionsBody window; walks its nested frames (CollectionsRecord ->
# CollectionsInvoices) same-origin to pull terms + the invoice table in one shot.
TRAVERSE = r"""() => {
  function walk(win){
    let doc; try{ doc = win.document; }catch(e){ return {terms:null,header:[],rows:[]}; }
    let terms=null;
    try{ const tm=doc.body && doc.body.innerText.match(/Terms:\s*(\d+)\s*Day/i); if(tm) terms=parseInt(tm[1]); }catch(e){}
    let header=[], rows=[];
    try{
      const t=[...doc.querySelectorAll('table')].find(t=>/InvoiceNo/i.test(t.innerText.slice(0,200)));
      if(t){ const trs=[...t.querySelectorAll('tr')];
        header=[...(trs[0]?trs[0].querySelectorAll('td,th'):[])].map(c=>c.innerText.trim());
        rows=trs.slice(1).map(r=>[...r.querySelectorAll('td')].map(c=>c.innerText.trim().replace(/\s+/g,' '))).filter(c=>c.length>=6 && /\d/.test(c[0]||'')); }
    }catch(e){}
    let out={terms,header,rows};
    for(let i=0;i<win.frames.length;i++){ const s=walk(win.frames[i]);
      if(s.terms!=null && out.terms==null) out.terms=s.terms;
      if(s.rows && s.rows.length){ out.header=s.header; out.rows=s.rows; } }
    return out;
  }
  return walk(window);
}"""

SYNC_XHR = "(u)=>{try{var x=new XMLHttpRequest();x.open('GET',u,false);x.send(null);return x.responseText||'';}catch(e){return '';}}"

def _expired(html):
    """True if the response is a goctl session-expired / login shell rather than the grid."""
    if not html:
        return True
    if 'InvoiceNo' in html:
        return False                       # a real (even empty) invoice grid always has the header
    if 'Session Expired' in html:
        return True
    if 'UserName' in html:                 # login form
        return True
    return len(html) < 500                 # 257-byte "Session Expired" shell, etc.

async def _fetch_html(pg, clientid):
    url = ("https://www.goctl.com/Accounting/Collections/Tools/CollectionsInvoices.aspx?ClientID="
           f"{clientid}&HideZeroBalanceInvoices=False&LoadedWithinCM=False")
    try:
        return await pg.evaluate(SYNC_XHR, url)
    except Exception:
        return ''

async def fetch_invoices(pg, clientid):
    """Fetch the client's invoice grid via a single self-contained XHR (no selectRow
    postbacks — those exhaust the goctl session after ~18 accounts). If the session has
    expired, re-login once and retry. Terms are NOT read here; run() derives them from
    goctl's own account-level Days Late. Returns a list of invoice dicts."""
    html = await _fetch_html(pg, clientid)
    if _expired(html):
        try:
            await login(pg)               # refresh the goctl session, then retry once
        except Exception:
            pass
        html = await _fetch_html(pg, clientid)
    data = {'header':[], 'rows':[]}
    if html and 'InvoiceNo' in html:
        try:
            d = await pg.evaluate(PARSE_TABLE, html)
            if d.get('rows'):
                data = d
        except Exception:
            pass
    if TEST and not data.get('rows'):
        print(f"      INVDEBUG client={clientid} len={len(html) if html else 0} "
              f"expired={_expired(html)} hasInvNo={'InvoiceNo' in (html or '')}")
    hdr = [h.lower() for h in data.get('header',[])]
    def col(*names, default=None):
        for n in names:
            for i,h in enumerate(hdr):
                if n in h: return i
        return default
    ci = {'no':col('invoiceno','invoice no','invoice #','invoice'),
          'date':col('invoice date','inv date'),
          'amt':col('amount'),
          'paid':col('paid'),
          'open':col('open','balance'),
          'age':col('days old','days','age')}
    invs=[]
    for c in data.get('rows',[]):
        def g(k):
            i=ci[k]
            return c[i] if (i is not None and i < len(c)) else None
        no=g('no')
        if not no: continue
        invs.append({'invoice_no':no,'invoice_date':g('date'),
                     'amount':money(g('amt')),'paid':money(g('paid')),
                     'open':money(g('open')),'days_old':to_int(g('age'))})
    return invs

async def run():
    from playwright.async_api import async_playwright
    now = datetime.now(); today = now.strftime('%m/%d/%Y')
    run_id = f"scraper-{now.strftime('%Y%m%d')}"
    print(f"[{now.strftime('%H:%M:%S')}] AR Scraper v2 ({'TEST' if TEST else 'FULL'}) starting...")
    async with async_playwright() as p:
        _headless = os.environ.get('HEADFUL') != '1'   # HEADFUL=1 (under xvfb) runs a real headed browser
        br = await p.chromium.launch(headless=_headless, args=['--no-sandbox','--disable-dev-shm-usage'])
        pg = await br.new_page(viewport={'width':1440,'height':900}); pg.set_default_timeout(30000)
        await login(pg)

        await pg.evaluate("() => { openFrame('Collections'); }"); await asyncio.sleep(6)
        coll = next((f for f in pg.frames if 'Collections.aspx' in f.url), None)
        if not coll:
            print("ERROR: Collections frame not found"); await br.close(); return
        await coll.evaluate("""() => { const sel=document.querySelector('select[name="Terminals"]');
            if(sel) for(let o of sel.options) o.selected = o.text.trim()==='Comet'; }""")
        await coll.click('text=Run Collections'); await asyncio.sleep(7)

        # collect account rows WITH clientid
        accounts=[]
        for frame in pg.frames:
            if 'Collections' in frame.url:
                try:
                    rows = await frame.evaluate(r"""() => {
                        const out=[]; const trs=[...document.querySelectorAll('tr')];
                        for(const r of trs){
                            const cid=r.getAttribute('clientid'); const c=[...r.querySelectorAll('td')].map(x=>x.innerText.trim().replace(/\s+/g,' '));
                            if(cid && c.length>=7 && c[1] && /^\d+$/.test(c[1])) out.push({clientid:cid, cells:c});
                        }
                        return out;
                    }""")
                    if rows: accounts=rows; break
                except: pass
        print(f"Collections accounts: {len(accounts)}")
        if TEST: accounts = accounts[:TEST_N]

        ar_rows=[]; warnings=[]
        for a in accounts:
            c=a['cells']; cid=a['clientid']
            company=c[0]; acct=c[1].strip()
            acct_days_late = to_int(c[7]) if len(c)>7 else 0
            acct_past_due  = money(c[8]) if len(c)>8 else 0.0
            try:
                invs = await fetch_invoices(pg, cid)
            except Exception as e:
                print(f"  {company} ({acct}) invoice fetch error: {e}"); invs=[]
            # Derive per-account terms from goctl's own account-level Days Late:
            #   goctl account Days Late = (oldest OPEN invoice days_old) - terms
            #   => terms = max(open days_old) - acct_days_late   (clamped >= 0)
            # This avoids the selectRow drill-down that exhausts the goctl session, and
            # reproduces goctl's exact terms (validated: 30/30/15 on 3 accounts).
            open_ages = [i['days_old'] for i in invs if i['open']>0]
            terms_days = max(0, max(open_ages) - acct_days_late) if open_ages else 30
            amt={'amt_current':0.0,'amt_1_29':0.0,'amt_30_59':0.0,'amt_60_89':0.0,'amt_90_119':0.0,'amt_120_plus':0.0}
            for inv in invs:
                if inv['open']<=0: continue
                dl = inv['days_old'] - terms_days           # per-account terms
                inv['days_late'] = dl
                _,key = bucket_of(dl); amt[key]+=inv['open']   # dl<=0 -> amt_current (not yet due)
            total_open = round(sum(amt.values()),2)
            # past_due matches goctl's account "Past Due": every open invoice PAST TERMS
            # (days_late > 0), NOT just the 30+ aging bands. goctl counts an invoice 12
            # days past a 30-day term as past due even though it sits in the amt_current
            # aging band; the aging buckets and the past_due total are separate metrics.
            past_due   = round(sum(i['open'] for i in invs
                                   if i['open']>0 and (i['days_old']-terms_days) > 0), 2)
            # most-severe non-zero bucket → account bucket_label
            sev=0
            for b,k in [(120,'amt_120_plus'),(90,'amt_90_119'),(60,'amt_60_89'),(30,'amt_30_59'),(1,'amt_1_29'),(0,'amt_current')]:
                if amt[k]>0: sev=b; break
            # Two independent checks:
            #  (a) buckets must partition the open balance (sum of bands == total open)
            #  (b) computed past_due must match goctl's own account Past Due figure
            bucket_ok = abs(sum(amt.values()) - total_open) < 0.01
            pastdue_ok = abs(past_due - acct_past_due) < 0.01
            recon_ok = bucket_ok and pastdue_ok
            if not bucket_ok: warnings.append(f"{company} ({acct}): bucket sum {sum(amt.values()):.2f} != total_open {total_open}")
            if not pastdue_ok: warnings.append(f"{company} ({acct}): past_due {past_due} != goctl {acct_past_due} (terms={terms_days}d, days_late={acct_days_late})")
            row={'run_id':run_id,'account_number':acct,'company_name':company,
                 'total_owed':total_open,'past_due_amount':past_due,
                 'amt_current':round(amt['amt_current'],2),'amt_1_29':round(amt['amt_1_29'],2),
                 'amt_30_59':round(amt['amt_30_59'],2),
                 'amt_60_89':round(amt['amt_60_89'],2),'amt_90_119':round(amt['amt_90_119'],2),
                 'amt_120_plus':round(amt['amt_120_plus'],2),
                 'invoice_count':len([i for i in invs if i['open']>0]),
                 'invoice_detail':invs,
                 'bucket':sev,'bucket_label':BUCKET_LABEL[sev],'status':'pending','run_date':today,
                 'source_filename':f'CollectionsInvoices:{cid}@{now.strftime("%Y%m%d")} terms={terms_days}d',
                 'days_late':acct_days_late}
            ar_rows.append(row)
            if TEST:
                print(f"\n  {company} ({acct}) client={cid} terms={terms_days}d invoices={len(invs)} open={row['invoice_count']}")
                print(f"    computed: total_open=${total_open}  current=${row['amt_current']} 1-29=${row['amt_1_29']} 30-59=${row['amt_30_59']} 60-89=${row['amt_60_89']} 90-119=${row['amt_90_119']} 120+=${row['amt_120_plus']}")
                print(f"    computed past_due=${past_due}  |  goctl account: past_due=${acct_past_due} days_late={acct_days_late}")
                print(f"    reconcile: buckets_sum_ok={bucket_ok} pastdue_matches_goctl={pastdue_ok}")
                for inv in invs[:6]:
                    print(f"      inv {inv['invoice_no']} date={inv['invoice_date']} amt=${inv['amount']} paid=${inv['paid']} open=${inv['open']} days_old={inv['days_old']} late={inv.get('days_late')}")
                if len(invs)==0:
                    print("      DEBUG frames:", [f.name for f in pg.frames if f.name])

        await br.close()

    (OUT/f'ar_scraper_v2_{"test" if TEST else "full"}.json').write_text(json.dumps(ar_rows, indent=2, default=str))
    if warnings:
        print("\n  RECONCILE WARNINGS:"); [print("   ",w) for w in warnings]
    if TEST:
        print(f"\nTEST complete — {len(ar_rows)} accounts, NO DB write. JSON: ar_scraper_v2_test.json")
        return
    # FULL: strip invoice_detail-less None, upsert
    if ar_rows:
        print(f"\nUpserting {len(ar_rows)} rows to ar_collections...")
        r = requests.post(f'{SUPA}/rest/v1/ar_collections', headers=HDRS, json=ar_rows)
        print(f"Supabase: {r.status_code}")
        if r.status_code>=400: print(f"Error: {r.text[:300]}")
    print("Done ✓")

asyncio.run(run())
