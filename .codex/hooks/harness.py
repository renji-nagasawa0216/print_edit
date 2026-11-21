#!/usr/bin/env python3
"""Codex hook dispatcher and local workflow state."""
import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

STAGES = ("rd", "mk", "st", "im", "vf", "sr", "ship")
STATES = ("running", "waiting", "passed", "failed", "skipped", "cancelled")
ROLES = {"tc-judge", "spec-challenger"}
SEPARATORS = set(";&|()")


def project(cwd):
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=3,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else Path(cwd)


def state_dir(root):
    return root / ".codex" / "harness-state"


def branch(root):
    result = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True, text=True, timeout=3,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=3,
    )
    return result.stdout.strip() if result.returncode == 0 else "(no branch)"


def branch_state(root, name):
    return state_dir(root) / hashlib.sha256(name.encode()).hexdigest()


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path, value):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False,
    ) as stream:
        temp = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def now():
    return datetime.now(timezone.utc).isoformat()


def session_key(session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
        raise ValueError("無効なセッション ID")
    return session_id


def git_args(words):
    if not words or Path(words[0]).name != "git":
        return []
    args = words[1:]
    while args and args[0].startswith("-"):
        skip = 2 if args[0] in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"} else 1
        args = args[skip:]
    return args


def risky_command(command):
    """Check common direct invocations. Shell indirection is outside this guard."""
    if len(command) > 100_000:
        return None
    lexer = shlex.shlex(command.replace("\\\n", "").replace("\n", " ; "),
                        posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    words = []
    for token in [*tokens, ";"]:
        if set(token) <= SEPARATORS and token:
            reason = risky_invocation(words)
            if reason:
                return reason
            words = []
        else:
            words.append(token)
    return None


def risky_invocation(words):
    while words and (words[0] in {"env", "command", "exec", "sudo", "nohup"}
                     or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", words[0])):
        words = words[1:]
    args = git_args(words)
    flags = set(args[1:])
    if args[:1] == ["push"] and (
        flags & {"-f", "--force", "-d", "--delete", "--mirror"}
        or any(arg.startswith(("+", ":")) for arg in args[1:])
    ):
        return "履歴の強制更新・リモート参照の削除・mirror push をガードしました。"
    if args[:1] == ["reset"] and "--hard" in flags:
        return "git reset --hard は作業差分を失う可能性があります。"
    if args[:1] == ["clean"] and any(
        flag == "--force" or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", flag) for flag in flags
    ) and not flags & {"--dry-run", "-n"} and not any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", f) for f in flags):
        return "強制 git clean をガードしました。先に dry run で対象を確認してください。"
    if args[:1] == ["branch"] and flags & {"-D", "--force"}:
        return "強制ブランチ操作をガードしました。"
    if args[:2] == ["worktree", "remove"] and flags & {"--force", "-f"}:
        return "worktree の強制撤去をガードしました。"
    if words and Path(words[0]).name == "gh" and words[1:3] in (["repo", "delete"], ["release", "delete"]):
        return "GitHub リポジトリ・リリースの削除をガードしました。"
    return None


def hook_context(event, content):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": content}}


def startup(root, event, data):
    current_branch = branch(root)
    directory = branch_state(root, current_branch)
    run = read(directory / "run.json", {})
    tasks = read(state_dir(root) / "tasks.json", {})
    lines = []
    if run.get("branch") == current_branch and run.get("status") not in {None, "cancelled"}:
        lines.append(f"開発工程の記録があります。工程 {run['stage']}、状態 {run['status']}。"
                     " 依頼がこの作業の続きであれば harness.py status で保存済みの根拠と再開地点を確認してください。")
    handoff = read(directory / "handoff.json", {})
    if handoff.get("branch") == current_branch:
        path = root / handoff.get("path", "")
        if path.is_file() and path.resolve().is_relative_to(root.resolve()):
            lines.append(f"前回の引き継ぎ: {json.dumps(str(path.relative_to(root)), ensure_ascii=False)}。"
                         " 現在の依頼に関係する場合に参照してください。")
    pending = [key for key, task in sorted(tasks.items()) if task["status"] == "pending"]
    if pending and data.get("source") != "compact":
        lines.append("未着手タスク ID: " + ", ".join(pending[:10])
                     + "。現在の依頼に該当する場合は harness.py task list を確認してください。")
    if lines and data.get("session_id"):
        lines.append("現在のセッション ID: " + session_key(data["session_id"]))
    return hook_context(event, "\n".join(lines)) if lines else {}


def stop(root, data):
    if data.get("stop_hook_active") or not (data.get("last_assistant_message") or "").rstrip().endswith("[harness:continue]"):
        return {}
    current_branch = branch(root)
    directory = branch_state(root, current_branch)
    session = session_key(data.get("session_id"))
    with locked(directory):
        path = directory / "continuation.json"
        request = read(path, {})
        run = read(directory / "run.json", {})
        if (request.get("session") != session or request.get("branch") != current_branch
                or run.get("status") != "running" or request.get("stage") != run.get("stage")):
            return {}
        path.unlink()
    return {"decision": "block", "reason": "保存済みの工程を確認し、現在の依頼範囲でローカル作業を一度続けてください。判断待ちや外部操作の権限は従来どおりです。"}


def dispatch(data):
    event = data.get("hook_event_name")
    if event == "PreToolUse":
        arguments = data.get("tool_input") or {}
        if data.get("tool_name") != "Bash" or not isinstance(arguments.get("command"), str):
            return {}
        reason = risky_command(arguments["command"])
        if reason:
            return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
        return {}
    if event == "SubagentStart" and data.get("agent_type") in ROLES:
        return hook_context(event, "親から渡された要件・決定事項・ケースだけを根拠にしてください。"
                            " 作業ツリー、実装差分、Git 履歴へのアクセスは作業指示上の対象外です。")
    if event == "UserPromptSubmit" and re.search(r"(?<!\w)\$go\b", data.get("prompt") or ""):
        return hook_context(event, "工程の記録に使える現在のセッション ID: " + session_key(data["session_id"]))
    if event in {"SessionStart", "Stop"}:
        root = project(data["cwd"])
        if event == "SessionStart":
            return startup(root, event, data)
        return stop(root, data)
    return {}


def record_stage(directory, current_branch, args):
    history_path = directory / "metrics.json"
    path = directory / "run.json"
    previous = read(path, {})
    if previous.get("branch") != current_branch:
        previous = {}
    timestamp = now()
    entry = {"branch": current_branch, "stage": args.stage, "status": args.status,
             "note": args.note, "at": timestamp}
    if previous.get("stage") == args.stage:
        elapsed = datetime.fromisoformat(timestamp) - datetime.fromisoformat(previous["at"])
        entry["seconds_since_previous_event"] = round(elapsed.total_seconds(), 3)
    history = read(history_path, [])
    history.append(entry)
    write(history_path, history)
    write(path, entry)
    return entry


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("metrics")
    stage = commands.add_parser("stage")
    stage.add_argument("stage", choices=STAGES)
    stage.add_argument("status", choices=STATES)
    stage.add_argument("note", nargs="?", default="")
    handoff = commands.add_parser("handoff")
    handoff.add_argument("path", type=Path)
    resume = commands.add_parser("continue")
    resume.add_argument("session_id")
    task = commands.add_parser("task")
    sub = task.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    for action in ("add", "claim", "release", "done"):
        operation = sub.add_parser(action)
        operation.add_argument("id", type=session_key)
        if action == "add":
            operation.add_argument("title")
            operation.add_argument("done_when")
        else:
            operation.add_argument("owner", type=session_key)
    args = parser.parse_args()
    root = project(Path.cwd())
    current_branch = branch(root)
    directory = state_dir(root) if args.command == "task" else branch_state(root, current_branch)
    if args.command == "status":
        result = read(directory / "run.json", {})
        result = result if result.get("branch") == current_branch else {}
    elif args.command == "metrics":
        result = [entry for entry in read(directory / "metrics.json", []) if entry["branch"] == current_branch]
    elif args.command == "task" and args.action == "list":
        result = read(directory / "tasks.json", {})
    else:
        with locked(directory):
            if args.command == "stage":
                result = record_stage(directory, current_branch, args)
                if args.status != "running":
                    (directory / "continuation.json").unlink(missing_ok=True)
            elif args.command == "handoff":
                path = args.path.resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file():
                    raise ValueError("作業ツリー内の既存ファイルを指定してください。")
                result = {"branch": current_branch, "path": str(path.relative_to(root.resolve()))}
                write(directory / "handoff.json", result)
            elif args.command == "continue":
                run = read(directory / "run.json", {})
                if run.get("status") != "running" or run.get("branch") != current_branch:
                    raise ValueError("進行中の工程がありません。")
                result = {"branch": current_branch, "stage": run["stage"], "session": session_key(args.session_id)}
                path = directory / "continuation.json"
                if read(path, {}).get("session") not in {None, result["session"]}:
                    raise ValueError("別セッションの継続要求が既に登録されています。")
                write(path, result)
            else:
                path = directory / "tasks.json"
                tasks = read(path, {})
                if args.action == "add":
                    if args.id in tasks:
                        raise ValueError("同じ ID のタスクがあります。")
                    result = tasks[args.id] = {"title": args.title, "done_when": args.done_when, "status": "pending"}
                else:
                    result = tasks[args.id]
                    if args.action == "claim" and result["status"] == "pending":
                        result.update(status="claimed", owner=args.owner)
                    elif args.action in {"release", "done"} and result["status"] == "claimed" and result.get("owner") == args.owner:
                        result["status"] = "pending" if args.action == "release" else "done"
                        result.pop("owner")
                    else:
                        raise ValueError("現在の状態または担当者が操作と一致しません。")
                write(path, tasks)
    return result


if __name__ == "__main__":
    try:
        result = dispatch(json.load(sys.stdin)) if sys.argv[1:] == ["hook"] else cli()
        print(json.dumps(result, ensure_ascii=False))
    except (KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
