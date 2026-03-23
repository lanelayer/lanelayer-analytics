#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


INTERVIEW_QUESTIONS = [
    "What type of application do you want to build?",
    "What are the core features and functionality you need?",
    "What data needs to be stored persistently?",
    "What are the key business rules or logic?",
    "Are there any specific requirements or constraints?",
    "What programming language do you prefer?",
]


@dataclass
class Turn:
    role: str
    message: str


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def load_lane_prompt(repo_root: Path, api_url: str) -> str:
    prompt_path = repo_root / "scripts" / "default-prompt.txt"
    content = prompt_path.read_text(encoding="utf-8")
    return content.replace("{{API_URL}}", api_url.rstrip("/"))


def load_scenario(repo_root: Path, scenario_path: Path) -> Dict[str, Any]:
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    terminal = raw["terminal"]
    cmd_outputs: Dict[str, str] = {}
    for cmd, rel in terminal["command_outputs"].items():
        p = (repo_root / rel).resolve()
        cmd_outputs[cmd] = p.read_text(encoding="utf-8")
    raw["terminal"] = {**terminal, "command_outputs": cmd_outputs}
    return raw


def codex_exec_jsonl(
    *,
    workspace: Path,
    prompt: str,
    thread_id: Optional[str] = None,
    sandbox: str = "workspace-write",
    full_auto: bool = True,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Run codex exec with JSONL output and return (thread_id, events).

    We set permissions to allow writing inside the workspace so the lane prompt can create journey.log.
    """
    base = [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        sandbox,
        "--cd",
        str(workspace),
    ]
    if full_auto:
        base.insert(3, "--full-auto")

    if thread_id is None:
        cmd = base + [prompt]
    else:
        cmd = ["codex", "exec", "resume", thread_id, "--json"]
        if full_auto:
            cmd.append("--full-auto")
        cmd += ["--sandbox", sandbox, "--cd", str(workspace), prompt]

    p = subprocess.run(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"codex exec failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
        )

    events: List[Dict[str, Any]] = []
    tid: Optional[str] = None
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        evt = json.loads(line)
        events.append(evt)
        if evt.get("type") == "thread.started":
            tid = evt.get("thread_id")

    if tid is None:
        # Sometimes resume runs may not emit thread.started; keep prior thread_id.
        tid = thread_id
    if not tid:
        raise RuntimeError("could not determine thread_id from codex --json output")
    return tid, events


def extract_codex_agent_messages(events: List[Dict[str, Any]]) -> List[str]:
    msgs: List[str] = []
    for evt in events:
        item = evt.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            text = item["text"].strip()
            if text:
                msgs.append(text)
    return msgs


def looks_like_multiple_questions(text: str) -> bool:
    numbered = len(re.findall(r"(?m)^\s*\d+\.\s+", text))
    if numbered >= 2:
        return True
    matched = sum(1 for q in INTERVIEW_QUESTIONS if q.lower() in text.lower())
    return matched >= 2


def build_terminal_agent_bootstrap(profile: Dict[str, str], command_outputs: Dict[str, str]) -> str:
    outputs_preview = "\n".join([f"- {k}" for k in sorted(command_outputs.keys())])
    return (
        "You are TerminalAgent. You are not the lane agent.\n"
        "You are the developer sitting at a terminal, interacting with the lane agent.\n\n"
        "Developer profile (use these facts consistently):\n"
        f"- App type: {profile.get('app_type','unknown')}\n"
        f"- Core features: {profile.get('core_features','unknown')}\n"
        f"- Persistent data: {profile.get('persistent_data','unknown')}\n"
        f"- Business rules: {profile.get('business_rules','unknown')}\n"
        f"- Constraints: {profile.get('constraints','unknown')}\n"
        f"- Language: {profile.get('language','unknown')}\n\n"
        "Rules:\n"
        "- Reply with ONLY your next terminal message (no analysis, no extra formatting).\n"
        "- If the lane agent asks you to run a command, do NOT actually run anything.\n"
        "- Instead, paste the canned output if it is available.\n"
        "- Available canned command outputs:\n"
        f"{outputs_preview}\n"
    )


def terminal_agent_next_input(
    *,
    workspace: Path,
    terminal_thread: str,
    lane_agent_message: str,
    command_outputs: Dict[str, str],
) -> str:
    msg_l = lane_agent_message.lower()
    if "lane --help" in msg_l or ("run" in msg_l and "--help" in msg_l and "lane" in msg_l):
        out = command_outputs.get("lane --help")
        if out:
            return f"Ran `lane --help`:\n\n{out}"

    prompt = (
        "LaneAgent just said:\n"
        "<<<\n"
        f"{lane_agent_message}\n"
        ">>>\n\n"
        "What do you type next in the terminal? Reply with ONLY the next terminal message."
    )
    _, ev = codex_exec_jsonl(
        workspace=workspace,
        prompt=prompt,
        thread_id=terminal_thread,
        sandbox="read-only",
        full_auto=True,
    )
    msgs = extract_codex_agent_messages(ev)
    return msgs[-1] if msgs else ""


def check_journey_log(workspace: Path) -> Tuple[bool, List[str]]:
    failures: List[str] = []
    jl = workspace / "journey.log"
    if not jl.exists():
        return False, ["journey.log not created"]

    text = jl.read_text(encoding="utf-8", errors="replace")
    required_headers = [
        "## Session:",
        "### Interview",
        "### Requirements Summary",
        "### CLI",
        "### Build",
        "### Local Test Gate",
        "### Deploy",
        "### Resilience",
        "### End State",
    ]
    for h in required_headers:
        if h not in text:
            failures.append(f"journey.log missing section header: {h}")
    return len(failures) == 0, failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="https://analytics.lanelayer.com/")
    ap.add_argument(
        "--scenario",
        default=str(Path(__file__).parent / "scenarios" / "basic.json"),
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    if _which("codex") is None:
        raise SystemExit("error: Codex CLI 'codex' is not installed or not on PATH")
    if _which("git") is None:
        raise SystemExit("error: git is required for codex exec runs")

    lane_prompt = load_lane_prompt(repo_root, args.api_url)
    scenario = load_scenario(repo_root, Path(args.scenario))

    turns: List[Turn] = []
    invariants = {
        "journey_log_used": False,
        "interview_one_question_at_a_time": True,
        "no_parent_directory_access": True,
        "local_test_gate_enforced": True,
    }
    notable_failures: List[str] = []

    with tempfile.TemporaryDirectory(prefix="lanelayer_prompt_sim_codex_") as td:
        ws = Path(td)

        # Codex requires a git repo check in many configurations; init a safe empty repo.
        subprocess.run(["git", "init"], cwd=str(ws), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        command_outputs = dict(scenario["terminal"]["command_outputs"])
        profile = dict(scenario["terminal"]["developer_profile"])

        # Boot TerminalAgent thread (read-only).
        terminal_boot = build_terminal_agent_bootstrap(profile, command_outputs)
        terminal_thread, _ = codex_exec_jsonl(workspace=ws, prompt=terminal_boot, thread_id=None, sandbox="read-only", full_auto=True)

        # Boot LaneAgent thread (workspace write allowed).
        thread_id, events = codex_exec_jsonl(workspace=ws, prompt=lane_prompt, thread_id=None, sandbox="workspace-write", full_auto=True)
        for m in extract_codex_agent_messages(events):
            turns.append(Turn("LaneAgent", m))
            if looks_like_multiple_questions(m):
                invariants["interview_one_question_at_a_time"] = False
                notable_failures.append("LaneAgent asked multiple interview questions in one message")

        max_turns = int(scenario.get("stop_after", {}).get("max_turns", 18))

        while len(turns) < max_turns:
            last_assistant = next((t.message for t in reversed(turns) if t.role == "LaneAgent"), "")
            reply = terminal_agent_next_input(
                workspace=ws,
                terminal_thread=terminal_thread,
                lane_agent_message=last_assistant,
                command_outputs=command_outputs,
            )
            if not reply.strip():
                break
            turns.append(Turn("Terminal", reply))

            thread_id, ev = codex_exec_jsonl(workspace=ws, prompt=reply, thread_id=thread_id, sandbox="workspace-write", full_auto=True)
            for m in extract_codex_agent_messages(ev):
                turns.append(Turn("LaneAgent", m))
                if looks_like_multiple_questions(m):
                    invariants["interview_one_question_at_a_time"] = False
                    notable_failures.append("LaneAgent asked multiple interview questions in one message")
                if "cd .." in m.lower() or "parent directory" in m.lower() or "scan the workspace" in m.lower():
                    invariants["no_parent_directory_access"] = False
                    notable_failures.append("LaneAgent attempted parent-directory/workspace scanning behavior")

        ok_jl, jl_failures = check_journey_log(ws)
        invariants["journey_log_used"] = ok_jl
        notable_failures.extend(jl_failures)

        overall_score = 10
        if not invariants["journey_log_used"]:
            overall_score -= 4
        if not invariants["interview_one_question_at_a_time"]:
            overall_score -= 2
        if not invariants["no_parent_directory_access"]:
            overall_score -= 2
        if overall_score < 0:
            overall_score = 0

        report = {
            "engine": "codex",
            "scenario": scenario.get("name", "unknown"),
            "overall_score": overall_score,
            "overall_rationale": "Two real CLI agents (LaneAgent + TerminalAgent) run a multi-turn simulation; invariants determine score.",
            "invariants": invariants,
            "transcript": [{"role": t.role, "message": t.message} for t in turns],
            "notable_failures": list(dict.fromkeys(notable_failures)),
        }

        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

