"""Turn a Claude Code session transcript (.jsonl) into a readable markdown build log.

Keeps every prompt the user typed and every message the agent wrote; folds each run of tool calls
into a collapsible one-line-per-call list; drops hidden reasoning, raw tool output and text the
harness injected on the user's behalf (skill instructions, IDE notices, image metadata, the
automatic compaction summary), so nothing is attributed to the user that they did not type.
Scrubs emails, local user paths and key-like strings.

Usage: python scripts/export_history.py <session.jsonl> docs/ai-build-history.md
"""
import json
import re
import sys
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
USERPATH = re.compile(r"(?i)(c:[\\/]+users[\\/]+)[^\\/\s\"']+")
KEYLIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|hf_[0-9A-Za-z]{20,})")
TAGS = re.compile(r"<(system-reminder|ide_opened_file|ide_selection|task-notification)>.*?</\1>", re.S)
INJECTED = ("Base directory for this skill", "[Image: original", "<task-notification>", "<command-",
            "Caveat: The messages below")
MIDTURN = re.compile(r"^The user sent a new message while you were working:\s*(.*?)\s*(?:This is how Claude Code surfaces.*)?$", re.S)
COMPACT = "This session is being continued from a previous conversation"


def scrub(s: str) -> str:
    s = EMAIL.sub("<email>", s)
    s = USERPATH.sub(r"\1<user>", s)
    return KEYLIKE.sub("<secret>", s)


def tool_line(name: str, inp: dict) -> str:
    desc = inp.get("description") or ""
    if name in ("Write", "Edit", "Read"):
        target = Path(inp.get("file_path", "")).name
        return f"`{name}` {target}" + (f": {desc}" if desc else "")
    if name in ("Bash", "PowerShell"):
        cmd = (inp.get("command", "").strip().splitlines() or [""])[0][:140]
        return f"`{name}` {desc or cmd}"
    if name == "AskUserQuestion":
        return "`AskUserQuestion` " + " / ".join(q.get("question", "")[:120] for q in inp.get("questions", []))
    if name == "Skill":
        return f"`Skill` {inp.get('skill', '')}"
    return f"`{name}` {desc or json.dumps(inp)[:120]}"


def user_text(ev: dict, txt: str) -> str | None:
    """The part of a user-role text block the user actually typed, or None."""
    if ev.get("isMeta") or ev.get("isCompactSummary"):
        return None
    txt = txt.strip()
    if any(txt.startswith(p) for p in INJECTED):
        return None
    m = MIDTURN.match(txt)
    if m:
        txt = m.group(1)
    txt = TAGS.sub("", txt)
    txt = re.sub(r"\[Image: source: [^\]]*\]", "[screenshot attached]", txt)
    txt = re.sub(r"\[Image #\d+\]", "[screenshot attached]", txt)
    return txt.strip() or None


def main(src: str, dst: str) -> None:
    out = ["# AI build history\n",
           "FINN was built in one Claude Code session (model: Claude Opus 5.5) on 15 Nov 2026.",
           "This is that session, condensed but not rewritten: every prompt I typed and every message the agent",
           "wrote, in order. Each run of tool calls (file writes, shell commands, test runs) is folded into a",
           "collapsible list with one line per call. Raw tool output, hidden reasoning and text the tool injected",
           "automatically are left out; personal paths, emails and keys are scrubbed.\n", "---\n"]
    n_tools = n_prompts = 0
    seen: set[str] = set()
    tools: list[str] = []

    def flush():
        if tools:
            out.append(f"\n<details><summary>{len(tools)} tool call{'s' if len(tools) > 1 else ''}</summary>\n")
            out.extend(tools)
            out.append("\n</details>\n")
            tools.clear()

    for line in Path(src).read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        role = msg.get("role") or ev.get("type")
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            sig = f"{t}:" + (c.get("id") or c.get("tool_use_id") or (str(role) + ":" + str(c.get("text", ""))[:400]))
            if sig in seen:
                continue
            seen.add(sig)
            if role == "user" and t == "text":
                raw = c.get("text", "")
                if raw.strip().startswith(COMPACT) or ev.get("isCompactSummary"):
                    flush()
                    out.append("\n> _Context compacted here: the conversation had grown too long, so Claude Code "
                               "replaced the earlier part with an automatic summary (not shown) and continued._\n")
                    continue
                txt = user_text(ev, raw)
                if txt:
                    flush()
                    n_prompts += 1
                    out.append(f"\n### 🧑 Me\n\n{scrub(txt)}\n")
            elif role == "user" and t == "tool_result":
                body = c.get("content")
                texts = [body] if isinstance(body, str) else [cc.get("text", "") for cc in (body or []) if isinstance(cc, dict)]
                for tx in texts:
                    if "have been answered" in tx[:200]:
                        flush()
                        out.append(f"\n> **My answer:** {scrub(tx[:700])}\n")
            elif role == "assistant" and t == "text" and c.get("text", "").strip():
                flush()
                out.append(f"\n**🤖 Claude:** {scrub(c['text'].strip())}\n")
            elif role == "assistant" and t == "tool_use":
                n_tools += 1
                tools.append(f"- {scrub(tool_line(c.get('name', ''), c.get('input') or {}))}")
    flush()
    out.append(f"\n---\n_{n_prompts} prompts, {n_tools} tool calls in total._\n")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {dst} ({n_prompts} prompts, {n_tools} tool calls)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
