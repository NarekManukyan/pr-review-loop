#!/usr/bin/env python3
"""Minimal stdio MCP server exposing slack-send to Claude Desktop.

Zero external dependencies — speaks newline-delimited JSON-RPC 2.0 over stdio and
shells out to the existing msg.sh / send.sh (same token in ~/.slack-upload-token),
so message/file logic stays in one place.

Tools:
  slack_send_message(target, message, thread_ts?)
  slack_send_file(file_path, target, comment?, thread_ts?)

Register in Claude Desktop (claude_desktop_config.json):
  "mcpServers": {
    "slack-send": { "command": "python3",
      "args": ["<abs path>/.claude/skills/slack-send/scripts/mcp_server.py"] }
  }
`bash install.sh --desktop` does this for you.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MSG = os.path.join(HERE, "msg.sh")
SEND = os.path.join(HERE, "send.sh")
PROTOCOL = "2024-11-05"

TARGET_DESC = "me | @username | Uxxxx (user id → DM) | #channel-name | Cxxxx/Dxxxx/Gxxxx (raw id)"
TOOLS = [
    {
        "name": "slack_send_message",
        "description": "Send a Slack message (DM, channel, or thread reply) as the token owner (you).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": TARGET_DESC},
                "message": {"type": "string", "description": "Message text (Slack mrkdwn: *bold*, _italic_, `code`, <url|label>)."},
                "thread_ts": {"type": "string", "description": "Optional parent message ts to reply in a thread (e.g. 1783423834.995569)."},
            },
            "required": ["target", "message"],
        },
    },
    {
        "name": "slack_send_file",
        "description": "Upload a LOCAL file to Slack (DM, channel, or thread) as the token owner (you). The MCP connector cannot upload files; this can.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to a local file to upload."},
                "target": {"type": "string", "description": TARGET_DESC},
                "comment": {"type": "string", "description": "Optional text posted with the file."},
                "thread_ts": {"type": "string", "description": "Optional parent message ts to post the file into a thread."},
            },
            "required": ["file_path", "target"],
        },
    },
]


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        return True, f"failed to run: {e}"
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode != 0, out.strip() or ("error" if p.returncode else "ok")


def call_tool(name, args):
    if name == "slack_send_message":
        cmd = [MSG, args["target"], args["message"]]
        if args.get("thread_ts"):
            cmd.append(args["thread_ts"])
        return run(cmd)
    if name == "slack_send_file":
        cmd = [SEND, args["file_path"], args["target"], args.get("comment", "")]
        if args.get("thread_ts"):
            cmd.append(args["thread_ts"])
        return run(cmd)
    return True, f"unknown tool: {name}"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "slack-send", "version": "1.0.0"},
            }})
        elif method == "notifications/initialized":
            pass  # notification, no response
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                is_err, text = call_tool(name, args)
            except Exception as e:  # noqa: BLE001
                is_err, text = True, f"error: {e}"
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_err,
            }})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
