"""Phase 0 (AI Responder) — mine the GHL two-way SMS corpus into an eval dataset.

The AI Responder handoff (AI_RESPONDER_HANDOFF.md §9 Phase 0) calls for an
offline, zero-compliance-risk pass over the real conversation corpus:

  1. A TYPE_SMS-only view of ghl.ConversationMessages (drop the TYPE_ACTIVITY_*
     opportunity/contact log noise — ~56% of "messages" are not real texts).
  2. The two-way SMS threads (both inbound AND outbound TYPE_SMS) mined into
     (context -> human reply) examples we can later have the agent attempt and
     score against the real human reply.

Read-only by construction: connects as the `dcr_ro` login via
fub_mcp.config.ro_connection_string(). No writes touch the warehouse.

Output (data/exports/sms_eval/, gitignored — these bodies are real PII):
  - threads.jsonl        one line per two-way thread, full ordered SMS turns
  - reply_examples.jsonl one line per "human reply" opportunity (the eval set)
  - summary.json         aggregate stats only (safe to read/share)

Console output is aggregates ONLY — never message bodies (DATA_RULES §7 PII).

Run:
  .venv/bin/python scripts/mine_sms_threads.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyodbc

from fub_mcp.config import ro_connection_string

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "exports" / "sms_eval"

# Reply-latency floor (seconds) above which an outbound reply is more likely a
# human agent than an auto-responder. ~95% of replies land under 2 min (machine
# cadence); the slower tail is the candidate human "gold" set.
HUMAN_LATENCY_MIN_SEC = 120

# All TYPE_SMS messages belonging to a thread that has at least one inbound AND
# one outbound TYPE_SMS — i.e. a genuine back-and-forth. Ordered for replay.
QUERY = """
WITH sms AS (
    SELECT ConversationId, ContactId, LocationId, Direction, Body,
           DateAddedUtc, MessageId
    FROM ghl.ConversationMessages
    WHERE MessageType = 'TYPE_SMS'
),
twoway AS (
    SELECT ConversationId
    FROM sms
    GROUP BY ConversationId
    HAVING SUM(CASE WHEN Direction = 'inbound'  THEN 1 ELSE 0 END) > 0
       AND SUM(CASE WHEN Direction = 'outbound' THEN 1 ELSE 0 END) > 0
)
SELECT s.ConversationId, s.ContactId, s.LocationId, s.Direction, s.Body,
       s.DateAddedUtc, s.MessageId
FROM sms s
JOIN twoway t ON t.ConversationId = s.ConversationId
ORDER BY s.ConversationId, s.DateAddedUtc, s.MessageId
"""


def _iso(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v) if v else None


def fetch_messages() -> list[dict[str, Any]]:
    """Pull every two-way-thread SMS as ordered dict rows (read-only login)."""
    conn = pyodbc.connect(ro_connection_string(), autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(QUERY)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def group_threads(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group ordered message rows into {conversation_id: {meta + turns}}.

    Contact/Location are constant within a thread, captured from the first row.
    """
    threads: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r["ConversationId"]
        if cid not in threads:
            threads[cid] = {
                "contact_id": r["ContactId"],
                "location_id": r["LocationId"],
                "turns": [],
            }
        threads[cid]["turns"].append(
            {
                "direction": r["Direction"],
                "ts": _iso(r["DateAddedUtc"]),
                "body": (r["Body"] or "").strip(),
                "message_id": r["MessageId"],
            }
        )
    return threads


def _runs(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive same-direction turns into runs (a "turn" of speech)."""
    runs: list[dict[str, Any]] = []
    for t in turns:
        if runs and runs[-1]["direction"] == t["direction"]:
            runs[-1]["turns"].append(t)
        else:
            runs.append({"direction": t["direction"], "turns": [t]})
    return runs


def _latency_sec(in_ts: str | None, out_ts: str | None) -> float | None:
    if not in_ts or not out_ts:
        return None
    try:
        return (datetime.fromisoformat(out_ts) - datetime.fromisoformat(in_ts)).total_seconds()
    except ValueError:
        return None


def reply_examples(meta: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every outbound run immediately preceded by an inbound run = a reply example.

    context = all turns before the lead's latest inbound run; latest_inbound =
    that run; human_reply = the outbound run the agent actually sent next.
    """
    runs = _runs(turns)
    examples: list[dict[str, Any]] = []
    cursor = 0  # index into the flat turn list, tracking where each run begins
    run_starts = []
    for run in runs:
        run_starts.append(cursor)
        cursor += len(run["turns"])

    for i, run in enumerate(runs):
        if run["direction"] != "outbound" or i == 0:
            continue
        prev = runs[i - 1]
        if prev["direction"] != "inbound":
            continue
        reply_bodies = [t["body"] for t in run["turns"] if t["body"]]
        if not reply_bodies:
            continue
        inbound_bodies = [t["body"] for t in prev["turns"] if t["body"]]
        if not inbound_bodies:
            continue
        context = turns[: run_starts[i - 1]]  # everything before the latest inbound
        last_in_ts = prev["turns"][-1]["ts"]
        reply_ts = run["turns"][0]["ts"]
        examples.append(
            {
                "thread_id": meta["thread_id"],
                "contact_id": meta["contact_id"],
                "location_id": meta["location_id"],
                "example_index": len(examples),
                "context": [
                    {"direction": t["direction"], "ts": t["ts"], "body": t["body"]}
                    for t in context
                ],
                "latest_inbound": inbound_bodies,
                "latest_inbound_ts": last_in_ts,
                "human_reply": reply_bodies,
                "human_reply_first": reply_bodies[0],
                "response_latency_sec": _latency_sec(last_in_ts, reply_ts),
            }
        )
    return examples


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Pulling two-way SMS threads (read-only dcr_ro)...")
    rows = fetch_messages()
    threads = group_threads(rows)
    print(f"  {len(rows):,} SMS messages across {len(threads):,} two-way threads")

    threads_path = OUT_DIR / "threads.jsonl"
    examples_path = OUT_DIR / "reply_examples.jsonl"
    gold_path = OUT_DIR / "human_gold.jsonl"

    n_examples = 0
    n_gold = 0
    thread_len_total = 0
    latencies: list[float] = []
    with threads_path.open("w", encoding="utf-8") as tf, \
         examples_path.open("w", encoding="utf-8") as ef, \
         gold_path.open("w", encoding="utf-8") as gf:
        for cid, thread in threads.items():
            turns = thread["turns"]
            first = turns[0]
            meta = {
                "thread_id": cid,
                "contact_id": thread["contact_id"],
                "location_id": thread["location_id"],
            }
            thread_len_total += len(turns)
            tf.write(json.dumps({
                "thread_id": cid,
                "contact_id": meta["contact_id"],
                "location_id": meta["location_id"],
                "message_count": len(turns),
                "inbound_count": sum(1 for t in turns if t["direction"] == "inbound"),
                "outbound_count": sum(1 for t in turns if t["direction"] == "outbound"),
                "first_ts": first["ts"],
                "last_ts": turns[-1]["ts"],
                "turns": turns,
            }, ensure_ascii=False) + "\n")

            for ex in reply_examples(meta, turns):
                line = json.dumps(ex, ensure_ascii=False) + "\n"
                ef.write(line)
                n_examples += 1
                lat = ex["response_latency_sec"]
                if lat is not None:
                    latencies.append(lat)
                    # >2 min reply latency = plausibly a human agent typing, not
                    # an auto-responder. This subset is the quality-calibration
                    # "gold" set (see AI_RESPONDER_HANDOFF.md §3.1).
                    if lat > HUMAN_LATENCY_MIN_SEC:
                        gf.write(line)
                        n_gold += 1

    latencies.sort()
    median_lat = latencies[len(latencies) // 2] if latencies else None
    # Latency buckets: <30s and 30s-2m are almost certainly automated sends
    # (REI Reply / GHL workflows), not a human agent typing. This segmentation
    # tells us how much of the "human reply" corpus is really the incumbent bot.
    buckets = {"<30s": 0, "30s-2m": 0, "2-10m": 0, "10-60m": 0, "1-24h": 0, ">24h": 0}
    for s in latencies:
        if s < 30:
            buckets["<30s"] += 1
        elif s < 120:
            buckets["30s-2m"] += 1
        elif s < 600:
            buckets["2-10m"] += 1
        elif s < 3600:
            buckets["10-60m"] += 1
        elif s < 86400:
            buckets["1-24h"] += 1
        else:
            buckets[">24h"] += 1
    auto_like = buckets["<30s"] + buckets["30s-2m"]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "ghl.ConversationMessages WHERE MessageType='TYPE_SMS'",
        "two_way_threads": len(threads),
        "total_sms_messages": len(rows),
        "avg_messages_per_thread": round(thread_len_total / len(threads), 2) if threads else 0,
        "reply_examples": n_examples,
        "human_gold_examples": n_gold,
        "human_gold_latency_min_threshold": HUMAN_LATENCY_MIN_SEC // 60,
        "reply_latency_sec_median": median_lat,
        "reply_latency_min_median": round(median_lat / 60, 1) if median_lat else None,
        "reply_latency_buckets": buckets,
        "likely_automated_replies": auto_like,
        "likely_automated_pct": round(100 * auto_like / len(latencies), 1) if latencies else None,
        "outputs": {
            "threads": str(threads_path.relative_to(OUT_DIR.parents[2])),
            "reply_examples": str(examples_path.relative_to(OUT_DIR.parents[2])),
            "human_gold": str(gold_path.relative_to(OUT_DIR.parents[2])),
        },
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"  wrote {len(threads):,} threads -> {threads_path.name}")
    print(f"  wrote {n_examples:,} reply examples -> {examples_path.name}")
    print(f"  wrote {n_gold:,} human-gold examples (>{HUMAN_LATENCY_MIN_SEC // 60}m latency) "
          f"-> {gold_path.name}")
    if median_lat:
        print(f"  median reply latency: {summary['reply_latency_min_median']} min")
    print(f"  summary -> {OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
