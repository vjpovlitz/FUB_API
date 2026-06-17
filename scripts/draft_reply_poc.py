"""Phase 0 (AI Responder) — draft-reply prototype + LLM-as-judge eval.

The wedge (AI_RESPONDER_HANDOFF.md §1, §13.2): given a lead's inbound text plus
the prior thread, can Claude draft a *better* next SMS than what was actually
sent? For ~95% of the mined corpus "what was sent" is the incumbent
auto-responder (REI Reply / GHL workflows; see §3.1), so beating it is exactly
on-mission. The `--pool gold` set is the ~258 slow-reply (likely-human) examples.

Pipeline, per sampled example:
  1. Build a contextual drafting prompt from the thread (a real-estate ISA
     persona + the conversation transcript ending at the lead's latest inbound).
  2. Generate the agent's next SMS with Claude (the *drafter*).
  3. Have Claude judge the AI draft against the actually-sent reply (the *judge*),
     scoring both on 5 dimensions and picking a winner. A/B order is randomized
     per example to cancel position bias.
  4. Aggregate: AI-draft win-rate + mean scores.

Cost control: defaults to a cheaper model (claude-sonnet-4-6), a small sample
(15), and prompt-caches the static system prompts. `--dry-run` builds every
prompt and prints the structure (bodies redacted) WITHOUT calling the API — use
it to validate prompt construction for free.

Output (data/exports/sms_eval/, gitignored — contains real message bodies):
  - draft_poc_report.json   full per-example records (prompts, draft, scores)
  - draft_poc_report.md     human-readable summary + a few redaction-free samples
Console output is aggregates only (no PII).

Run:
  .venv/bin/python scripts/draft_reply_poc.py --dry-run            # free, validates prompts
  .venv/bin/python scripts/draft_reply_poc.py                      # real, 15 examples
  .venv/bin/python scripts/draft_reply_poc.py --pool gold -n 30    # human-gold subset
  ANTHROPIC_DRAFT_MODEL=claude-opus-4-8 .venv/bin/python scripts/draft_reply_poc.py

Env (loaded from .env): ANTHROPIC_API_KEY (required for real runs),
  ANTHROPIC_DRAFT_MODEL / ANTHROPIC_JUDGE_MODEL (default claude-sonnet-4-6).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "exports" / "sms_eval"

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

DEFAULT_MODEL = "claude-sonnet-4-6"  # user chose a cheaper model for iterating
DRAFT_MODEL = os.getenv("ANTHROPIC_DRAFT_MODEL", DEFAULT_MODEL)
JUDGE_MODEL = os.getenv("ANTHROPIC_JUDGE_MODEL", DEFAULT_MODEL)

# --- prompts ------------------------------------------------------------------
DRAFT_SYSTEM = """You are an inside sales agent (ISA) for Dana Capital Realty, a \
residential real-estate brokerage. You follow up with leads by SMS text message.

Your job: read the conversation so far and write the single next text message to \
send to the lead. Goals, in order: be genuinely helpful and human, answer any \
question the lead asked, qualify gently (timeline, budget, motivation, \
financing) when natural, and move toward a concrete next step (a call, a \
showing, sending listings).

Rules:
- Output ONLY the text of the message to send. No preamble, no quotes, no labels.
- Write like a real person texting: warm, concise, plain language. No markdown.
- One or two short sentences. It's a text, not an email.
- Never invent specific facts (addresses, prices, appointment times) that aren't \
in the conversation. If you'd need info you don't have, ask for it.
- Don't be pushy or salesy. Don't repeat what was already said."""

JUDGE_SYSTEM = """You are an expert sales manager at a real-estate brokerage \
grading SMS replies that an agent could send to a lead. You are shown the \
conversation so far and TWO candidate next messages (A and B). Score each on a \
1-5 scale (5 = excellent) on:
- relevance: does it address the lead's latest message and the situation?
- context_use: does it use the conversation history well (no contradictions, \
no repetition, picks up threads)?
- advances: does it move the relationship forward (qualify, book, helpfully \
answer) without being pushy?
- tone: natural, warm, human, text-appropriate (not robotic or salesy)?
- overall: your holistic judgment of which message a top-performing agent would \
actually send.

Then pick the winner: "A", "B", or "tie". Be discerning — reserve "tie" for \
genuinely indistinguishable cases. Judge only the message quality; ignore length \
differences unless they hurt the message. Respond via the structured schema."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_a": {"$ref": "#/$defs/scores"},
        "candidate_b": {"$ref": "#/$defs/scores"},
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string"},
    },
    "required": ["candidate_a", "candidate_b", "winner", "rationale"],
    "additionalProperties": False,
    "$defs": {
        "scores": {
            "type": "object",
            "properties": {
                "relevance": {"type": "integer"},
                "context_use": {"type": "integer"},
                "advances": {"type": "integer"},
                "tone": {"type": "integer"},
                "overall": {"type": "integer"},
            },
            "required": ["relevance", "context_use", "advances", "tone", "overall"],
            "additionalProperties": False,
        }
    },
}


def render_transcript(example: dict[str, Any]) -> str:
    """Render the thread context + latest inbound as a Lead/Agent transcript."""
    lines = []
    for turn in example["context"]:
        who = "Lead" if turn["direction"] == "inbound" else "Agent"
        body = turn["body"].strip()
        if body:
            lines.append(f"{who}: {body}")
    for body in example["latest_inbound"]:
        lines.append(f"Lead: {body.strip()}")
    return "\n".join(lines)


def draft_user_prompt(transcript: str) -> str:
    return (
        "Conversation so far (most recent message last):\n\n"
        f"{transcript}\n\n"
        "Write the single next text message to send to the lead. "
        "Output only the message text."
    )


def judge_user_prompt(transcript: str, msg_a: str, msg_b: str) -> str:
    return (
        "Conversation so far (most recent message last):\n\n"
        f"{transcript}\n\n"
        "Candidate A (next message):\n"
        f"{msg_a}\n\n"
        "Candidate B (next message):\n"
        f"{msg_b}\n\n"
        "Score both candidates and pick the winner."
    )


# --- provider -----------------------------------------------------------------
class AnthropicProvider:
    """Thin wrapper over the Anthropic Messages API for draft + judge calls."""

    def __init__(self, draft_model: str, judge_model: str):
        import anthropic  # imported lazily so --dry-run needs no SDK/key
        self.client = anthropic.Anthropic()
        self.draft_model = draft_model
        self.judge_model = judge_model

    def draft(self, transcript: str) -> str:
        resp = self.client.messages.create(
            model=self.draft_model,
            max_tokens=300,
            system=[{"type": "text", "text": DRAFT_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": draft_user_prompt(transcript)}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    def judge(self, transcript: str, msg_a: str, msg_b: str) -> dict[str, Any]:
        resp = self.client.messages.create(
            model=self.judge_model,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=[{"type": "text", "text": JUDGE_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user",
                       "content": judge_user_prompt(transcript, msg_a, msg_b)}],
            output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)


# --- eval loop ----------------------------------------------------------------
@dataclass
class Result:
    thread_id: str
    transcript: str
    actual_reply: str
    ai_draft: str
    ai_label: str            # which slot ("A"/"B") the AI draft occupied
    judge: dict[str, Any]
    ai_won: bool | None      # True if judge picked the AI draft; None on tie/error
    error: str | None = None


DIMS = ["relevance", "context_use", "advances", "tone", "overall"]


def load_examples(pool: str) -> list[dict[str, Any]]:
    fname = "human_gold.jsonl" if pool == "gold" else "reply_examples.jsonl"
    path = OUT_DIR / fname
    if not path.exists():
        sys.exit(f"Missing {path}. Run scripts/mine_sms_threads.py first.")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def run_eval(provider: AnthropicProvider, examples: list[dict[str, Any]],
             rng: random.Random) -> list[Result]:
    results: list[Result] = []
    for i, ex in enumerate(examples, 1):
        transcript = render_transcript(ex)
        actual = ex["human_reply_first"]
        try:
            draft = provider.draft(transcript)
            # Randomize A/B slot so the judge can't infer which is the AI draft.
            ai_is_a = rng.random() < 0.5
            msg_a, msg_b = (draft, actual) if ai_is_a else (actual, draft)
            verdict = provider.judge(transcript, msg_a, msg_b)
            ai_label = "A" if ai_is_a else "B"
            winner = verdict["winner"]
            ai_won = None if winner == "tie" else (winner == ai_label)
            results.append(Result(ex["thread_id"], transcript, actual, draft,
                                  ai_label, verdict, ai_won))
            mark = "AI" if ai_won else ("tie" if ai_won is None else "human")
            print(f"  [{i}/{len(examples)}] winner={mark}", flush=True)
        except Exception as e:  # noqa: BLE001
            results.append(Result(ex["thread_id"], transcript, actual, "", "",
                                  {}, None, error=str(e)))
            print(f"  [{i}/{len(examples)}] ERROR: {e}", flush=True)
    return results


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def aggregate(results: list[Result]) -> dict[str, Any]:
    ok = [r for r in results if r.error is None and r.judge]
    ai_wins = sum(1 for r in ok if r.ai_won is True)
    human_wins = sum(1 for r in ok if r.ai_won is False)
    ties = sum(1 for r in ok if r.ai_won is None)
    decided = ai_wins + human_wins
    ai_scores = {d: [] for d in DIMS}
    human_scores = {d: [] for d in DIMS}
    for r in ok:
        ai_slot = "candidate_a" if r.ai_label == "A" else "candidate_b"
        human_slot = "candidate_b" if r.ai_label == "A" else "candidate_a"
        for d in DIMS:
            ai_scores[d].append(r.judge[ai_slot][d])
            human_scores[d].append(r.judge[human_slot][d])
    return {
        "scored": len(ok),
        "errors": len(results) - len(ok),
        "ai_wins": ai_wins,
        "human_wins": human_wins,
        "ties": ties,
        "ai_win_rate_decided": round(ai_wins / decided, 3) if decided else None,
        "ai_win_rate_all": round(ai_wins / len(ok), 3) if ok else None,
        "ai_mean_scores": {d: _mean(ai_scores[d]) for d in DIMS},
        "human_mean_scores": {d: _mean(human_scores[d]) for d in DIMS},
    }


def write_reports(meta: dict[str, Any], agg: dict[str, Any],
                  results: list[Result]) -> tuple[Path, Path]:
    json_path = OUT_DIR / "draft_poc_report.json"
    md_path = OUT_DIR / "draft_poc_report.md"
    json_path.write_text(json.dumps({
        "meta": meta, "aggregate": agg,
        "results": [{
            "thread_id": r.thread_id,
            "transcript": r.transcript,
            "actual_reply": r.actual_reply,
            "ai_draft": r.ai_draft,
            "ai_label": r.ai_label,
            "judge": r.judge,
            "ai_won": r.ai_won,
            "error": r.error,
        } for r in results],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Draft-reply POC report", "",
        f"- Generated: {meta['generated_at']}",
        f"- Pool: `{meta['pool']}` · sampled {meta['n']} of {meta['pool_size']}",
        f"- Drafter: `{meta['draft_model']}` · Judge: `{meta['judge_model']}`",
        "",
        "> Caveat: for the `full` pool ~95% of \"actual\" replies are the "
        "incumbent auto-responder, not a human (see handoff §3.1). The `gold` "
        "pool is the slow-reply human subset.",
        "> Self-preference: drafter and judge are the same model family — treat "
        "win-rate as directional, not absolute.",
        "",
        "## Result", "",
        "| Metric | Value |", "| --- | --- |",
        f"| Scored | {agg['scored']} (errors: {agg['errors']}) |",
        f"| AI draft wins | {agg['ai_wins']} |",
        f"| Actual-reply wins | {agg['human_wins']} |",
        f"| Ties | {agg['ties']} |",
        f"| **AI win-rate (decided)** | {agg['ai_win_rate_decided']} |",
        "",
        "## Mean scores (1-5)", "",
        "| Dimension | AI draft | Actual reply |", "| --- | --- | --- |",
    ]
    for d in DIMS:
        lines.append(f"| {d} | {agg['ai_mean_scores'][d]} | {agg['human_mean_scores'][d]} |")
    # A few full samples for eyeballing quality.
    lines += ["", "## Sample drafts (first 5)", ""]
    for r in [x for x in results if x.error is None][:5]:
        verdict = "AI" if r.ai_won else ("tie" if r.ai_won is None else "actual")
        lines += [
            f"**Thread `{r.thread_id[:10]}…`** — winner: {verdict}",
            "",
            "_Transcript (tail):_",
            "```",
            "\n".join(r.transcript.splitlines()[-6:]),
            "```",
            f"- **Actual reply:** {r.actual_reply}",
            f"- **AI draft:** {r.ai_draft}",
            f"- _Judge:_ {r.judge.get('rationale', '')}",
            "",
        ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def dry_run(examples: list[dict[str, Any]]) -> None:
    """Build + show prompts for the first 2 examples (bodies redacted). No API."""
    print("DRY RUN — no API calls. Showing constructed prompts (bodies redacted).\n")
    for i, ex in enumerate(examples[:2], 1):
        transcript = render_transcript(ex)
        red = "\n".join(
            f"{ln.split(':', 1)[0]}: [{len(ln.split(':', 1)[1].strip())} chars]"
            if ":" in ln else ln
            for ln in transcript.splitlines()
        )
        print(f"=== example {i} (thread {ex['thread_id'][:10]}…) ===")
        print(f"  context turns: {len(ex['context'])}  "
              f"latest_inbound msgs: {len(ex['latest_inbound'])}")
        print("  DRAFT system chars:", len(DRAFT_SYSTEM))
        print("  transcript (redacted):")
        for ln in red.splitlines():
            print("    " + ln)
        print(f"  actual reply: [{len(ex['human_reply_first'])} chars]")
        print()
    print(f"Would draft+judge {len(examples)} example(s) with "
          f"drafter={DRAFT_MODEL} judge={JUDGE_MODEL}.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Draft-reply POC + LLM judge.")
    ap.add_argument("--pool", choices=["full", "gold"], default="full",
                    help="full = all reply examples; gold = >2min latency (human-ish)")
    ap.add_argument("-n", "--num", type=int, default=15, help="sample size (default 15)")
    ap.add_argument("--seed", type=int, default=7, help="sampling/AB-order seed")
    ap.add_argument("--dry-run", action="store_true",
                    help="build + print prompts only; no API calls")
    args = ap.parse_args()

    examples = load_examples(args.pool)
    pool_size = len(examples)
    rng = random.Random(args.seed)
    sample = rng.sample(examples, min(args.num, pool_size))

    if args.dry_run:
        dry_run(sample)
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY not set. Add it to .env, or use --dry-run.")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        sys.exit("anthropic SDK missing. Run: pip install -e \".[agent]\"")

    print(f"Drafting + judging {len(sample)} example(s) from pool='{args.pool}' "
          f"(drafter={DRAFT_MODEL}, judge={JUDGE_MODEL})\n", flush=True)
    provider = AnthropicProvider(DRAFT_MODEL, JUDGE_MODEL)
    results = run_eval(provider, sample, rng)
    agg = aggregate(results)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool": args.pool, "pool_size": pool_size, "n": len(sample),
        "seed": args.seed, "draft_model": DRAFT_MODEL, "judge_model": JUDGE_MODEL,
    }
    json_path, md_path = write_reports(meta, agg, results)

    print("\n" + "=" * 60)
    print(f"  AI win-rate (decided): {agg['ai_win_rate_decided']}  "
          f"(AI {agg['ai_wins']} / actual {agg['human_wins']} / tie {agg['ties']})")
    print(f"  AI mean overall: {agg['ai_mean_scores']['overall']}  "
          f"actual mean overall: {agg['human_mean_scores']['overall']}")
    print(f"  errors: {agg['errors']}")
    print("=" * 60)
    print(f"Reports: {md_path}  +  {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
