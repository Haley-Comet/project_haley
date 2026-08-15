#!/usr/bin/env python3
"""
Weekly gold-corpus eval sweep.

Calls the eval_gold Edge Function once per bucket. eval_gold replays Agent turns
from gold_conversations through grade_output and writes rows to output_grades.
post_gold_eval_delta() then rolls those up and posts the delta to Discord #ops.

Golds are exemplars, so a HIGH pass rate is expected. A falling pass rate means
either the agent regressed or the rubric drifted — both worth knowing.

Baseline 2026-07-29: rubric v1 = 58.9% / 0.705, rubric v2 = 85.6% / 0.908 (same 90 turns).

Scheduled Mondays 04:00 UTC (Sunday 23:00 CT); the Discord post runs at 05:00 UTC.
Batched per bucket deliberately — one call across the whole corpus exceeds the
Edge Function wall-clock limit.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENV_FILE = "/opt/xcelerator/.env"
BUCKETS = ["complete_order", "dispatch_status", "ar", "quote"]
LIMIT = 12                 # conversations per bucket
MAX_TURNS = 2              # Agent turns graded per conversation
TIMEOUT = 280
RETRIES = 2


def load_env(path):
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def log(msg):
    print("[%s] gold-eval: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def call_eval(base, key, bucket):
    body = json.dumps({
        "bucket": bucket,
        "limit": LIMIT,
        "max_turns_per_convo": MAX_TURNS,
    }).encode()
    req = urllib.request.Request(base + "/functions/v1/eval_gold", data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("apikey", key)
    req.add_header("Content-Type", "application/json")

    last = None
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except Exception as exc:                       # noqa: BLE001
            last = exc
            if attempt < RETRIES:
                time.sleep(5 * (attempt + 1))
    raise last


def main():
    env = load_env(ENV_FILE)
    base = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_KEY", "")
    if not base or not key:
        log("FATAL: SUPABASE_URL / SUPABASE_KEY missing from %s" % ENV_FILE)
        return 1

    total_graded = total_passed = failed_buckets = 0
    violations = {}

    for bucket in BUCKETS:
        try:
            r = call_eval(base, key, bucket)
        except Exception as exc:                       # noqa: BLE001
            log("  %s: FAILED - %s" % (bucket, exc))
            failed_buckets += 1
            continue

        graded = r.get("turns_graded") or 0
        passed = r.get("passed") or 0
        total_graded += graded
        total_passed += passed
        for crit, n in (r.get("violations_by_criterion") or {}).items():
            violations[crit] = violations.get(crit, 0) + n

        log("  %s: %s graded, %s passed, pass_rate=%s, avg=%s"
            % (bucket, graded, passed, r.get("pass_rate"), r.get("avg_score")))

        # A criterion firing on nearly every turn is a rubric problem, not an agent
        # problem. This is exactly how the greeting-turn artifacts were caught.
        if graded:
            for crit, n in (r.get("violations_by_criterion") or {}).items():
                if n >= graded * 0.8:
                    log("    NOTE %s fired on %d/%d turns — check rubric calibration"
                        % (crit, n, graded))

    if not total_graded:
        log("complete: 0 turns graded across %d buckets — check ANTHROPIC_API_KEY on "
            "grade_output and that gold_conversations still has Agent turns" % len(BUCKETS))
        return 1

    pct = 100.0 * total_passed / total_graded
    log("complete: %d turns, %d passed (%.1f%%), %d bucket(s) failed"
        % (total_graded, total_passed, pct, failed_buckets))
    if violations:
        top = sorted(violations.items(), key=lambda kv: -kv[1])[:5]
        log("top violations: " + ", ".join("%s=%d" % (c, n) for c, n in top))

    return 1 if failed_buckets else 0


if __name__ == "__main__":
    sys.exit(main())
