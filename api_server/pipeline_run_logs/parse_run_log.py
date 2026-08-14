"""Parses a test_orchestrated_pipeline.py run log (as saved under pipeline_run_logs/) into
structured markdown tables: per-turn summary, per-iteration agent timing, and the full
memory load/evict/snapshot timeline -- the raw log has all of this already (every [ORCH]
line is a real decision with real GB numbers, every [agent iter N] line is a real timing),
this just extracts it into something reviewable at a glance instead of scrollback.

Usage: python parse_run_log.py <logfile> [-o output.md]
"""
import argparse
import re
import sys
from pathlib import Path

TURN_RE = re.compile(r"FULL PIPELINE -- language=(\w+) \(([^)]+)\)(?: \[([^\]]+)\])?")
QUERY_RE = re.compile(r"^\[PIPE\] query: (.*)$")
TRANSCRIBED_RE = re.compile(r"^\[PIPE\] transcribed \((\w+)\): (.*)$")
TRANSLATED_EN_RE = re.compile(r"^\[PIPE\] translated to English: (.*)$")
ITER_RE = re.compile(r"\[agent iter (\S+)\] load=(\d+)ms prefill=(\d+)ms \((\d+) tok\) gen=(\d+)ms \((\d+) tok\)")
TOOL_CALL_RE = re.compile(r"^\s+-> (\w+)\(")
ANSWER_RE = re.compile(r"^\[PIPE\] agent answer \(English, markdown-stripped\): (.*)$")
TRANSLATED_ANSWER_RE = re.compile(r"^\[PIPE\] translated answer \((\w+)\): (.*)$")
TURN_WALLCLOCK_RE = re.compile(r"\[PIPE\] total turn wall-clock: ([\d.]+)s")
AGENT_WALLCLOCK_RE = re.compile(r"\[ORCH\]\s+agent turn: ([\d.]+)s")
LOAD_RE = re.compile(r"\[ORCH\] LOAD\s+(\S+)\s+<- (.*)")
EVICT_RE = re.compile(r"\[ORCH\] EVICT\s+(\S+)\s+-> (.*)")
SNAPSHOT_RE = re.compile(r"\[ORCH\]\s+(startup|ready|steady-state ready.*?):\s*(.*total=[\d.]+GB.*)")
INFER_RE = re.compile(r"\[ORCH\]\s+(\w+) infer: ([\d.]+)s")
LOADED_STATE_RE = re.compile(r'"state":"?loaded"?|state=loaded|load_time_sec')


def parse(lines: list[str]) -> dict:
    turns = []
    cur_turn = None
    cur_iters = []
    events = []  # (turn_index_or_None, kind, text)

    # Answers are printed via print(f"...: {content}") where content itself contains embedded
    # "\n\n" paragraph breaks -- they span multiple physical lines in the log, not one. Track
    # which field (if any) is mid-capture and keep appending lines to it until the next
    # bracketed [ORCH]/[PIPE] marker line ends the block (blank lines within the answer are
    # legitimate paragraph breaks, not a stop condition).
    capturing = None  # None | "answer_en" | "answer_translated"

    for line in lines:
        line = line.rstrip("\n")

        if capturing is not None:
            if re.match(r"^\[(ORCH|PIPE)\]", line):
                capturing = None
            else:
                cur_turn[capturing] += "\n" + line
                continue

        m = TURN_RE.search(line)
        if m:
            if cur_turn is not None:
                cur_turn["iterations"] = cur_iters
                turns.append(cur_turn)
            cur_iters = []
            cur_turn = {
                "language": m.group(1), "language_name": m.group(2), "label": m.group(3),
                "query": None, "transcribed": None, "translated_en": None,
                "answer_en": None, "answer_translated": None,
                "turn_wallclock": None, "agent_wallclock": None,
            }
            continue

        m = QUERY_RE.match(line)
        if m and cur_turn is not None:
            cur_turn["query"] = m.group(1)
        m = TRANSCRIBED_RE.match(line)
        if m and cur_turn is not None:
            cur_turn["transcribed"] = m.group(2)
        m = TRANSLATED_EN_RE.match(line)
        if m and cur_turn is not None:
            cur_turn["translated_en"] = m.group(1)
        m = ANSWER_RE.match(line)
        if m and cur_turn is not None:
            cur_turn["answer_en"] = m.group(1)
            capturing = "answer_en"
        m = TRANSLATED_ANSWER_RE.match(line)
        if m and cur_turn is not None:
            cur_turn["answer_translated"] = m.group(2)
            capturing = "answer_translated"
        m = TURN_WALLCLOCK_RE.search(line)
        if m and cur_turn is not None:
            cur_turn["turn_wallclock"] = float(m.group(1))
        m = AGENT_WALLCLOCK_RE.search(line)
        if m and cur_turn is not None:
            cur_turn["agent_wallclock"] = float(m.group(1))

        m = ITER_RE.search(line)
        if m:
            cur_iters.append({
                "iter": m.group(1), "load_ms": int(m.group(2)), "prefill_ms": int(m.group(3)),
                "prefill_tok": int(m.group(4)), "gen_ms": int(m.group(5)), "gen_tok": int(m.group(6)),
                "tool": None,
            })
        m = TOOL_CALL_RE.match(line)
        if m and cur_iters:
            cur_iters[-1]["tool"] = m.group(1)

        m = LOAD_RE.search(line)
        if m:
            events.append((len(turns), "LOAD", f"{m.group(1)}: {m.group(2)}"))
        m = EVICT_RE.search(line)
        if m:
            events.append((len(turns), "EVICT", f"{m.group(1)}: {m.group(2)}"))
        m = SNAPSHOT_RE.search(line)
        if m:
            events.append((len(turns), "SNAPSHOT", m.group(2)))
        m = INFER_RE.search(line)
        if m:
            events.append((len(turns), "INFER", f"{m.group(1)}: {m.group(2)}s"))

    if cur_turn is not None:
        cur_turn["iterations"] = cur_iters
        turns.append(cur_turn)

    return {"turns": turns, "events": events}


def render_markdown(parsed: dict, source: str) -> str:
    turns = parsed["turns"]
    out = [f"# Pipeline run report\n\nSource log: `{source}`\n"]

    out.append("## Turn summary\n")
    out.append("| # | Lang | Label | Query (EN) | Turn wall-clock | Agent wall-clock | Tool calls |")
    out.append("|---|---|---|---|---|---|---|")
    for i, t in enumerate(turns, 1):
        q = (t["translated_en"] or t["query"] or "").replace("|", "\\|")
        if len(q) > 70:
            q = q[:67] + "..."
        tools = ", ".join(it["tool"] for it in t["iterations"] if it["tool"]) or "-"
        out.append(
            f"| {i} | {t['language']} | {t['label'] or ''} | {q} | "
            f"{t['turn_wallclock'] or '-'}s | {t['agent_wallclock'] or '-'}s | {tools} |"
        )

    out.append("\n## Per-iteration agent timing\n")
    out.append("| Turn | Iter | Load (ms) | Prefill (ms) | Prefill tok | Gen (ms) | Gen tok | Tool called |")
    out.append("|---|---|---|---|---|---|---|---|")
    for i, t in enumerate(turns, 1):
        for it in t["iterations"]:
            out.append(
                f"| {i} | {it['iter']} | {it['load_ms']} | {it['prefill_ms']} | {it['prefill_tok']} | "
                f"{it['gen_ms']} | {it['gen_tok']} | {it['tool'] or '-'} |"
            )

    out.append("\n## Memory load/evict/snapshot timeline\n")
    out.append("| Turn | Event | Detail |")
    out.append("|---|---|---|")
    for turn_idx, kind, text in parsed["events"]:
        out.append(f"| {turn_idx} | {kind} | {text.replace('|', chr(92) + '|')} |")

    def blockquote(text: str) -> str:
        # prefix EVERY line (including blank paragraph-break lines) with "> " so multi-
        # paragraph answers render as one continuous blockquote, not just the first line
        return "\n".join(f"> {ln}" if ln else ">" for ln in text.split("\n"))

    out.append("\n## Full answers (English)\n")
    for i, t in enumerate(turns, 1):
        out.append(f"**Turn {i}** ({t['label'] or t['language']}): {t.get('query') or t.get('translated_en') or ''}\n")
        out.append(blockquote(t["answer_en"] or "(no answer captured)") + "\n")
        if t.get("answer_translated"):
            out.append(f"\n*Translated:*\n\n{blockquote(t['answer_translated'])}\n")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logfile", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    args = ap.parse_args()

    lines = args.logfile.read_text(errors="replace").splitlines(keepends=True)
    parsed = parse(lines)
    md = render_markdown(parsed, args.logfile.name)

    out_path = args.output or args.logfile.with_suffix(".report.md")
    out_path.write_text(md)
    print(f"Wrote {out_path} ({len(parsed['turns'])} turns, {len(parsed['events'])} memory events)")


if __name__ == "__main__":
    main()
