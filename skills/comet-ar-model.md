# Comet AR / Collections Data Model (Read)

*Taught 2026-08-15 from facts verified live against the database that day. READ skill - answering "what does this account owe / what bucket / what's past due". No sending, no writing.*

## ar_collections - per-account AR snapshot per scraper run (37 cols)

Key fields: account_number, company_name, bucket (0/30/60/90/120) / bucket_label, total_owed, past_due_amount, invoice_count, invoice_detail (jsonb), aging columns amt_current, amt_30_59, amt_60_89, amt_90_119, amt_120_plus, days_old, days_late, plus collection-lifecycle fields (status in {pending, sent, skipped, expired}, call_attempted, reply_received, reply_classification, suppressed_until, gmail_thread_id). Latest snapshot = most recent run_date; runs are keyed run_id = scraper-YYYYMMDD.

**Bucket labels are one scheme** (Current, 30-59 Days, 60-89 Days, 90-119 Days, 120+ Days). A legacy second scheme (31_60, 61_90, 91_120, over_120) existed on pre-Aug-2026 rows and was backfilled away on 2026-08-15 - if you ever see it again, that is a regression worth flagging.

## WARNING - Known data caveats (do not skip)

1. **past_due_amount on raw rows is wrong for current-bucket accounts** - the scraper historically wrote past_due_amount = total_owed on every row. **Always read past-due figures through v_ar_latest**, which corrects bucket-0 accounts to $0. A scraper fix (per-bucket amounts) is specced but not yet shipped.
2. **amt_current ... amt_120_plus are NULL on all rows** until that scraper fix ships. NULL there means "row predates the fix", not "$0".
3. In invoices: **invoice_status is 'open' on every row and open_amount/paid_amount are unpopulated** - payment state is never updated. Do NOT use this table to decide whether an invoice is paid. It is reliable for: invoice existence, invoice_number, account_number, amount, invoice_date, and pdf_url (a stored PDF exists for every invoice since 2026-03-21).

## invoices - one row per invoice (16 cols)

invoice_number, account_number, amount, paid_amount, open_amount, invoice_status, invoice_date, period_end_date, pdf_url, pdf_filename, sent_to_email. Ingested from delivery emails (source = 'ctlEmail').

## Views to prefer over raw tables

- **v_ar_latest** - latest run, one row per account, corrected past_due_amount. This is what the Daily Ops Briefing and Agent Brain read. Use it for "what does X owe / who's past due".
- **v_ar_pastdue_invoices** - maps each currently past-due account to the stored invoice PDF(s) that make up its balance, with match_type (anchor_exact / amount_unique / window_sum / ambiguous) and attachable. Only trust attachable = true rows for "which invoice is past due".

Both views are service-role-only by design; they are not reachable with the public anon key.

## Related automation (context, not yours to trigger)

AR - Collections Processor (weekday 8am CT) sends reminder emails for status='pending', bucket>0, days_late>=45 rows and attaches matched invoice PDFs; AR - Invoice Copy Responder auto-serves invoice copies on verified customer replies. Reply state lands back on ar_collections (reply_received, reply_classification).
