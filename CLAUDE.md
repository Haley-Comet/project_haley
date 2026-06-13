# Comet Messenger - Haley 2.0 (project memory)

Operations platform for Comet Messenger Service (Chicago same-day courier).
Stack: n8n (VPS + Cloud), Supabase Postgres, Retell voice agents, Hostinger KVM4 VPS.

<!-- Keep this file under ~200 lines. Facts only - things we'd otherwise re-explain
     every session. Procedures and one-off context go in skills or .claude/rules/. -->

## Golden rules (do not violate without explicit go-ahead)

- **No secrets in this repo.** Never paste service-role keys, JWTs, webhook URLs,
  or passwords into CLAUDE.md, code, or commits. Secrets live in Vaultwarden /
  Supabase Vault. Refer to them by name (e.g. COMET_AGENT_SECRET), never by value.
- **Production changes are staging-first.** New n8n workflows are built in staging
  (Beelink, port 5679), exported as JSON, then imported to the VPS. Do not push
  straight to prod.
- **Ask before destructive or schema-altering actions** on prod (migrations, drops,
  bulk updates, revoking grants). Prepare the change; let a human apply it.

## Supabase

- Project ref: ykuzxqmshzoywvufynps.
- **DDL -> apply_migration. Reads/verification -> execute_sql.** Never run batched
  upsert SQL through MCP - those go through the SQL Editor.
- The orders table is always double-quoted: "Orders" (case-sensitive).
- Status codes: N=New/Active, R=Rated, S=Statemented, P=Paid, C=Cancelled.
  Revenue/active queries use status IN ('N','R','S','P') - do not silently drop N.
- **Every new public table needs explicit GRANTs + RLS policies in the same
  migration** (rule in force since the Oct 2026 rollout).
- After adding columns, run NOTIFY pgrst, 'reload schema';
- Schema-switching from n8n HTTP nodes uses Content-Profile / Accept-Profile
  headers - URL-only searches miss writes to customers.accounts.
- Upserts: Prefer: resolution=merge-duplicates + ?on_conflict=.

## Data architecture (source of truth)

- **Excelerator CSV is the permanent source of truth** for all order fields.
- Gmail delivery emails are **additive only** - may write photo_url,
  signature_raw, signature_type, signature_valid, delivered_at. Nothing else.

## n8n

- **Never use the SDK update_workflow / create_workflow** - known zero-node bug.
  Import via the UI three-dot menu (JSON) only. Matters most for complex
  workflows (Portal-Concierge-Agent).
- Before importing JSON, strip: id, versionId, active, pinData, meta.instanceId.
  After importing, set timezone to America/Chicago.
- VPS search_workflows matches names/descriptions only, not node content.
- Workflows with availableInMCP: false return no node data - toggle in UI first.

## Deploy

- Static site: upload to Hostinger public_html, then
  python3 /opt/deploy.py [portal|boardroom|accountupdate|ops|kirkland|all].

## People

- Haley - owner/architect/operator. Jim - owner/operator, customer relationships.
  Damien - on-camera/marketing content. Dan - external dev (Retell/n8n live prod).
  Cowork - executes from written handoffs.

## Operating principles

- Haley talks to the office; the office talks to the field. Order changes -> Haley
  calls dispatch, never drivers.
- Comet-only builds. Arrow Messengers is off the roadmap.
- Prefer owned, self-hosted, compounding systems over packaged SaaS. Avoid lock-in.
