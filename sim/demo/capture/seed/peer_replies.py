"""Peer replies from a session file: python -I peer_replies.py SESSION.jsonl OUT.json."""
import json, re, sys
last, out = None, []
for line in open(sys.argv[1]):
    e = json.loads(line)
    if e.get("type") == "assistant":
        for c in e["message"]["content"]:
            if c.get("type") == "tool_use":
                last = c["id"]
    a = e.get("attachment") or {}
    if a.get("type") == "queued_command" and "cross-session-message" in a.get("prompt", ""):
        m = re.match(r'<cross-session-message [^>]*from-name="([^"]+)"[^>]*>\n(.*)\n</cross-session-message>', a["prompt"], re.S)
        out.append({"after_tool_use_id": last, "from": m.group(1), "text": m.group(2)})
open(sys.argv[2], "w").write(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
