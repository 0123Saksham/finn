"""Turn a Claude Code session transcript (.jsonl) into a readable markdown build log.
Keeps user prompts, assistant messages and a one-line summary of every tool call;
drops hidden reasoning and bulky tool output; scrubs emails and local user paths.
Usage: python scripts/export_history.py <session.jsonl> docs/ai-build-history.md"""
import json
import re
import sys
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
USERPATH = re.compile(r"(?i)(c:[\\/]+users[\\/]+)[^\\/\s\"']+")
KEYLIKE = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|hf_[0-9A-Za-z]{20,})")


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
        cmd = inp.get("command", "").strip().splitlines()[0][:140]
        return f"`{name}` {desc or cmd}"
    if name == "AskUserQuestion":
        return "`AskUserQuestion` " + " / ".join(q.get("question", "")[:120] for q in inp.get("questions", []))
    return f"`{name}` {desc or json.dumps(inp)[:120]}"


def main(src: str, dst: str) -> None:
    out = ["# AI build history\n",
           "FINN was built in a single Claude Code session (model: Claude Opus 5.5) on 15 Nov 2026.",
           "This is that session, condensed: every prompt I typed, every message the agent wrote, and a one-line",
           "summary of each tool call (file writes, shell commands, test runs). Raw tool output and hidden",
           "reasoning are omitted for length; personal paths and emails are scrubbed.\n", "---\n"]
    n_tools = 0
    seen: set[str] = set()
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
            t = c.get("type")
            sig = f"{t}:" + (c.get("id") or c.get("tool_use_id") or (role + ":" + str(c.get("text", ""))[:400]))
            if sig in seen:
                continue
            seen.add(sig)
            if role == "user" and t == "text":
                txt = c["text"].strip()
                if txt.startswith("<") and ("system-reminder" in txt[:40] or "command-" in txt[:40]):
                    continue
                txt = re.sub(r"<system-reminder>.*?</system-reminder>", "", txt, flags=re.S).strip()
                if txt:
                    out.append(f"\n### 🧑 Me\n\n{scrub(txt)}\n")
            elif role == "user" and t == "tool_result":
                body = c.get("content")
                texts = [body] if isinstance(body, str) else [cc.get("text", "") for cc in (body or []) if isinstance(cc, dict)]
                for tx in texts:
                    if "have been answered" in tx[:200]:
                        out.append(f"\n> **My answer:** {scrub(tx[:700])}\n")
            elif role == "assistant" and t == "text" and c.get("text", "").strip():
                out.append(f"\n**🤖 Claude:** {scrub(c['text'].strip())}\n")
            elif role == "assistant" and t == "tool_use":
                n_tools += 1
                out.append(f"- {scrub(tool_line(c.get('name', ''), c.get('input') or {}))}")
    out.append(f"\n---\n_{n_tools} tool calls in total._\n")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {dst} ({n_tools} tool calls)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
