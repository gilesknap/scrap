"""Build the recorder's transcript.json, written-page.json, summary-page.json and
summary-day-page.json from the raw stream-json runs and API dumps.

    python -I build_transcript.py RAW_DIR TRANSCRIPT_DIR   (rerun.sh: _claude/demo-video sim/demo/transcript)
"""
import json, sys
from pathlib import Path

D = Path(sys.argv[1])  # the raw runs
T = Path(sys.argv[2])  # sim/demo/transcript: peer-replies.json in, the rest out
STEPS = [("01-find.jsonl", "/sc-find whiteboard"),
         ("02-answer.jsonl", "/sc-answer what's on my plate at home this week?"),
         ("03-write.jsonl", "/sc-write this weekend's house jobs as one todo checklist, most urgent first. Just post."),
         # segment 2: a small fix in ~/demo/tidy, then /sc-summarise (a fresh session)
         ("05-fix.jsonl", "Fix the issue in ISSUE.md on a branch, run the tests, and commit."),
         ("06-housejobs.jsonl", "Different thing: what's left on this weekend's house jobs?"),
         ("07-summarise.jsonl", "/sc-summarise"),
         ("08-post.jsonl", "yes"),
         # step f runs under the demo's own isolated config (CLAUDE_CONFIG_DIR=/root/demo-claude)
         ("09-summarise-day.jsonl", "/sc-summarise day"),
         ("10-post-day.jsonl", "yes")]
# replies from the two staged demo sessions: they reach the session as queued messages, which
# stream-json does not show; peer-replies.json has them from the session file, placed after
# the tool call they followed
PEERS = {}
if (T / "peer-replies.json").exists():
    for r in json.loads((T / "peer-replies.json").read_text()):
        PEERS.setdefault(r["after_tool_use_id"], []).append(r)
CWD = {f: "~/demo/tidy" for f, _ in STEPS[3:]}


def display(name, inp):
    """The tool call as Claude Code shows it: ● Bash(cmd), ● Update(file)."""
    base = lambda f: f.rsplit("/", 1)[-1]
    if name == "Bash":
        cmd = inp["command"]
        first = cmd.split("\n")[0]
        return f"Bash({first}{' …' if '\n' in cmd else ''})"
    if name in ("Edit", "MultiEdit"):
        return f"Update({base(inp['file_path'])})"
    if name in ("Read", "Write"):
        return f"{name}({base(inp['file_path'])})"
    if name.startswith("mcp__"):
        server, tool = name.split("__")[1:3]
        return f"{server} - {tool} (MCP)({args_summary(name, inp)})"
    return f"{name}({args_summary(name, inp)})"


def result_display(name, inp, content, tur, is_error):
    """The ⎿ line(s) under a call, trimmed as Claude Code trims them."""
    text = content if isinstance(content, str) else "".join(c.get("text", "") for c in content if c.get("type") == "text")
    if is_error:
        return "Error: " + text.removeprefix("Error: ").split(". ")[0] + "."
    if name in ("Edit", "MultiEdit") and isinstance(tur, dict):
        old, new = tur.get("oldString", ""), tur.get("newString", "")
        o, n = old.splitlines(), new.splitlines()
        common = [l for l in o if l in n]
        add, rem = len([l for l in n if l not in o]), len([l for l in o if l not in n])
        diff = [f"- {l}" for l in o if l not in n] + [f"+ {l}" for l in n if l not in o]
        head = f"Updated {inp['file_path'].rsplit('/', 1)[-1]} with {add} addition{'s' * (add != 1)}" + (f" and {rem} removal{'s' * (rem != 1)}" if rem else "")
        return head + "\n" + "\n".join(diff[:8]) + ("\n…" if len(diff) > 8 else "")
    if name == "Read":
        return f"Read {len(text.splitlines())} lines"
    if name == "Bash":
        lines = (tur.get("stdout", "") if isinstance(tur, dict) else text).splitlines()
        if not lines:
            return "(No content)"
        shown = lines[:4]
        return "\n".join(shown) + (f"\n… +{len(lines) - 4} lines" if len(lines) > 4 else "")
    if name.startswith(("mcp__", "ToolSearch")):
        return None
    try:
        text = json.loads(text)["message"].split(" (")[0]  # SendMessage: "“…” → name"
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    lines = text.splitlines()  # ListAgents, SendMessage and the like: their own text, trimmed
    return "\n".join(lines[:6]) + (f"\n… +{len(lines) - 6} lines" if len(lines) > 6 else "")

def args_summary(name, inp):
    if name == "ToolSearch":
        return inp.get("query", "")
    if name == "SendMessage":
        inp = {k: inp[k] for k in ("to", "message") if k in inp}
    return ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v) if len(v) < 90 else repr(v[:80] + '…')}"
                     for k, v in inp.items() if k not in ("key", "origin"))

def result_summary(name, content):
    if isinstance(content, list):
        refs = [c.get("tool_name") for c in content if c.get("type") == "tool_reference"]
        if refs:
            return "loaded " + ", ".join(refs)
        content = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    try:
        d = json.loads(content)
    except (TypeError, ValueError):
        return content[:200] + ("…" if len(content) > 200 else "")
    if "results" in d:
        r = d["results"]
        if not r:
            return "0 results"
        items = []
        for x in r[:6]:
            bits = [x.get("kind")] + ([f"due {x['due']}"] if x.get("due") else []) + ([x["priority"]] if x.get("priority") else [])
            items.append(f"{x['title']} ({', '.join(b for b in bits if b)})")
        return f"{len(r)} results: " + "; ".join(items) + (" …" if len(r) > 6 else "")
    if "page" in d:
        p = d["page"]
        extra = [p.get("kind")] + ([f"due {p['due']}"] if p.get("due") else []) + ([p["priority"]] if p.get("priority") else [])
        t = p.get("tasks") or {}
        if t.get("total"):
            extra.append(f"{t['done']}/{t['total']} ticked")
        title = (d.get("content") or {}).get("title") or p["slug"]
        return f"{title} · {', '.join(e for e in extra if e)} · tags {' '.join('#' + x for x in p.get('tags', []))}"
    if "text" in d and "meta" in d and "trash" in d:
        return f"{len(d['text'])} text, {len(d['meta'])} meta, {len(d['trash'])} trash revisions: " + "; ".join(
            f"{r.get('title') or r.get('slug')} ({r.get('author')})" for r in d["text"][:4]) + (" …" if len(d["text"]) > 4 else "")
    if "created" in d and "url" in d:
        return f"created: {d['url']}"
    if "tags" in d:
        tags = d["tags"]
        names = [f"#{t[0]} ({t[1]} pages)" if isinstance(t, list) else str(t) for t in tags][:10]
        return f"{len(tags)} tags: " + ", ".join(names) + (" …" if len(tags) > 10 else "")
    s = json.dumps(d, ensure_ascii=False)
    return s[:200] + "…"

steps = []
for fn, prompt in STEPS:
    names, events = {}, []
    for line in (D / fn).read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in ev["message"]["content"]:
                if c["type"] == "text" and c["text"].strip():
                    events.append({"type": "text", "text": c["text"]})
                elif c["type"] == "tool_use":
                    names[c["id"]] = (c["name"], c["input"])
                    events.append({"type": "tool_call", "name": c["name"], "args_summary": args_summary(c["name"], c["input"]),
                                   **({"display": display(c["name"], c["input"])} if fn in CWD else {}),
                                   **({"internal": True} if c["name"] == "ToolSearch" else {})})
        elif ev.get("type") == "user":
            content = ev["message"]["content"]
            if isinstance(content, list):
                for c in content:
                    if c.get("type") == "tool_result":
                        n, inp = names.get(c["tool_use_id"], ("", {}))
                        rd = result_display(n, inp, c["content"], ev.get("tool_use_result"), c.get("is_error")) if fn in CWD else None
                        pending = PEERS.get(c["tool_use_id"], [])
                        events.append({"type": "tool_result", "name": n, "summary": result_summary(n, c["content"]) if n.startswith(("mcp__", "ToolSearch")) else (rd or "").split("\n")[0],
                                       **({"display": rd} if rd else {}),
                                       **({"denied": True} if c.get("is_error") and "denied" in str(c["content"]) else {}),
                                       **({"internal": True} if n == "ToolSearch" else {})})
                        for r in pending:
                            events.append({"type": "peer_message", "from": r["from"], "text": r["text"],
                                           "display": f"← message from {r['from']}"})
    steps.append({"prompt": prompt, "raw": fn, **({"cwd": CWD[fn], "segment": 2} if fn in CWD else {"cwd": "~/demo", "segment": 1}), "events": events})
(T / "transcript.json").write_text(json.dumps({"note": "Real claude -p run (Claude Code, resumed session) against a throwaway scrap seeded with the sim's demo pages. Events marked internal are Claude Code's deferred-tool loading (ToolSearch); a terminal replay may hide them.", "steps": steps}, indent=1, ensure_ascii=False) + "\n")

p = json.loads((D / "written-page-api.json").read_text())
call = next(e for e in steps[2]["events"] if e["type"] == "tool_call" and e["name"] == "mcp__scrap__write")
(T / "written-page.json").write_text(json.dumps({k: p[k] for k in ("id", "slug", "title", "kind", "due", "priority", "tags", "fields", "created_at", "body")}
    | {"url": f"https://scrap.example.com/p/{p['slug']}"}, indent=1, ensure_ascii=False) + "\n")
for src, dst, extra in (("summary-page-api.json", "summary-page.json",
                          {"note": "/sc-summarise (current topic: the house-jobs check) appended a section to the house-jobs page instead of making a new page; body is the whole page after the append",
                           "appended_body": next(c["input"]["body"] for l in (D / "08-post.jsonl").read_text().splitlines() if l.startswith("{") and json.loads(l).get("type") == "assistant" for c in json.loads(l)["message"]["content"] if c.get("name") == "mcp__scrap__write")}),
                         ("summary-day-page-api.json", "summary-day-page.json", {})):
    s = json.loads((D / src).read_text())
    (T / dst).write_text(json.dumps({k: s[k] for k in ("id", "slug", "title", "kind", "tags", "fields", "rev", "created_at", "updated_at", "body")}
        | {"url": f"https://scrap.example.com/p/{s['slug']}"} | extra, indent=1, ensure_ascii=False) + "\n")
print("ok")
