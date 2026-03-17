#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
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

STEP_HEADERS = [
    "### Interview",
    "### Requirements Summary",
    "### Registration",
    "### CLI",
    "### Build",
    "### Local Test Gate",
    "### Deploy",
    "### Resilience",
    "### End State",
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
    email = profile.get("email", "dev@example.com")
    return (
        "You are TerminalAgent. You are not the lane agent.\n"
        "You are the developer sitting at a terminal, interacting with the lane agent.\n\n"
        "Developer profile (use these facts consistently):\n"
        f"- App type: {profile.get('app_type','unknown')}\n"
        f"- Core features: {profile.get('core_features','unknown')}\n"
        f"- Persistent data: {profile.get('persistent_data','unknown')}\n"
        f"- Business rules: {profile.get('business_rules','unknown')}\n"
        f"- Constraints: {profile.get('constraints','unknown')}\n"
        f"- Language: {profile.get('language','unknown')}\n"
        f"- Email: {email}\n\n"
        "Rules:\n"
        "- Reply with ONLY your next terminal message (no analysis, no extra formatting).\n"
        "- If the lane agent asks you to run a command, do NOT actually run anything.\n"
        "- Instead, paste the canned output if it is available.\n"
        "- Available canned command outputs:\n"
        f"{outputs_preview}\n\n"
        f"- When asked for your email address, respond with: {email}\n"
        "- When asked for a verification code, respond with: 123456\n"
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
        "### Registration",
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


def check_journey_log_progress(workspace: Path) -> Tuple[Dict[str, bool], List[str]]:
    """Check whether each journey.log phase has real content."""
    phases: Dict[str, bool] = {
        "interview_filled": False,
        "requirements_filled": False,
        "registration_filled": False,
        "cli_filled": False,
        "build_filled": False,
        "local_test_gate_filled": False,
        "deploy_filled": False,
        "end_state_filled": False,
    }
    failures: List[str] = []
    jl = workspace / "journey.log"
    if not jl.exists():
        failures.append("journey.log not created — all phases missing")
        return phases, failures

    text = jl.read_text(encoding="utf-8", errors="replace")
    text_l = text.lower()

    def _section_text(header: str) -> str:
        idx = text.find(header)
        if idx == -1:
            return ""
        start = idx + len(header)
        next_h = text.find("\n### ", start)
        return text[start:next_h].strip() if next_h != -1 else text[start:].strip()

    interview = _section_text("### Interview")
    if interview and "A:" in interview:
        phases["interview_filled"] = True
    else:
        failures.append("Interview phase has no answers")

    reqs = _section_text("### Requirements Summary")
    if reqs and reqs.lower().strip() != "unknown":
        phases["requirements_filled"] = True
    else:
        failures.append("Requirements Summary still unknown")

    registration = _section_text("### Registration")
    if "verified: yes" in registration.lower():
        phases["registration_filled"] = True
    else:
        failures.append("Registration phase not completed (not verified)")

    cli = _section_text("### CLI")
    if "installed: yes" in text_l and "version: unknown" not in text_l:
        phases["cli_filled"] = True
    else:
        failures.append("CLI phase not completed (not installed or version unknown)")

    build = _section_text("### Build")
    if build and "lane name: unknown" not in text_l:
        phases["build_filled"] = True
    else:
        failures.append("Build phase not completed (lane name still unknown)")

    test_gate = _section_text("### Local Test Gate")
    if "all passed: yes" in text_l:
        phases["local_test_gate_filled"] = True
    else:
        failures.append("Local Test Gate not passed")

    deploy = _section_text("### Deploy")
    if "container pushed to registry: yes" in text_l:
        phases["deploy_filled"] = True
    else:
        failures.append("Deploy phase not completed")

    end_state = _section_text("### End State")
    if "status: deployed" in text_l:
        phases["end_state_filled"] = True
    else:
        failures.append("End State not reached (status != deployed)")

    return phases, failures


def detect_last_step(journey_text: str) -> str:
    """Determine the last prompt step that has content in journey.log."""
    last = "none"
    for header in STEP_HEADERS:
        idx = journey_text.find(header)
        if idx == -1:
            continue
        start = idx + len(header)
        next_h = journey_text.find("\n### ", start)
        section = (
            journey_text[start:next_h].strip()
            if next_h != -1
            else journey_text[start:].strip()
        )
        if section and section.lower() != "unknown":
            last = header.replace("### ", "")
    return last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="https://lanelayer-analytics.fly.dev")
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
    stop_reason = "max_turns"

    start_time = time.time()

    with tempfile.TemporaryDirectory(prefix="lanelayer_prompt_sim_codex_") as td:
        ws = Path(td)

        subprocess.run(
            ["git", "init"],
            cwd=str(ws),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        command_outputs = dict(scenario["terminal"]["command_outputs"])
        profile = dict(scenario["terminal"]["developer_profile"])

        terminal_boot = build_terminal_agent_bootstrap(profile, command_outputs)
        terminal_thread, _ = codex_exec_jsonl(
            workspace=ws,
            prompt=terminal_boot,
            thread_id=None,
            sandbox="read-only",
            full_auto=True,
        )

        thread_id, events = codex_exec_jsonl(
            workspace=ws,
            prompt=lane_prompt,
            thread_id=None,
            sandbox="workspace-write",
            full_auto=True,
        )
        for m in extract_codex_agent_messages(events):
            turns.append(Turn("LaneAgent", m))
            if looks_like_multiple_questions(m):
                invariants["interview_one_question_at_a_time"] = False
                notable_failures.append(
                    "LaneAgent asked multiple interview questions in one message"
                )

        max_turns = int(scenario.get("stop_after", {}).get("max_turns", 18))

        while len(turns) < max_turns:
            last_assistant = next(
                (t.message for t in reversed(turns) if t.role == "LaneAgent"), ""
            )

            # Check for blocked/waiting state
            last_l = last_assistant.lower()
            if any(
                phrase in last_l
                for phrase in (
                    "standing by",
                    "just let me know",
                    "just drop a message",
                    "waiting for",
                    "once you get the",
                    "when the fix is live",
                )
            ):
                stop_reason = "blocked"
                notable_failures.append("LaneAgent reached a blocked/waiting state")
                break

            reply = terminal_agent_next_input(
                workspace=ws,
                terminal_thread=terminal_thread,
                lane_agent_message=last_assistant,
                command_outputs=command_outputs,
            )
            if not reply.strip():
                stop_reason = "terminal_silent"
                notable_failures.append("TerminalAgent returned empty response")
                break

            if "ESCALATED" in reply.upper() and "waiting for external input" in reply.lower():
                turns.append(Turn("Terminal", reply))
                stop_reason = "escalated"
                notable_failures.append(
                    "TerminalAgent escalated — no external service available"
                )
                break

            turns.append(Turn("Terminal", reply))

            thread_id, ev = codex_exec_jsonl(
                workspace=ws,
                prompt=reply,
                thread_id=thread_id,
                sandbox="workspace-write",
                full_auto=True,
            )
            for m in extract_codex_agent_messages(ev):
                turns.append(Turn("LaneAgent", m))
                if looks_like_multiple_questions(m):
                    invariants["interview_one_question_at_a_time"] = False
                    notable_failures.append(
                        "LaneAgent asked multiple interview questions in one message"
                    )
                if (
                    "cd .." in m.lower()
                    or "parent directory" in m.lower()
                    or "scan the workspace" in m.lower()
                ):
                    invariants["no_parent_directory_access"] = False
                    notable_failures.append(
                        "LaneAgent attempted parent-directory/workspace scanning behavior"
                    )

        duration = round(time.time() - start_time, 1)

        ok_jl, jl_failures = check_journey_log(ws)
        invariants["journey_log_used"] = ok_jl
        notable_failures.extend(jl_failures)

        phases, phase_failures = check_journey_log_progress(ws)
        notable_failures.extend(phase_failures)

        # Read journey.log content and copy out
        journey_log_text = ""
        jl_path = ws / "journey.log"
        if jl_path.exists():
            journey_log_text = jl_path.read_text(encoding="utf-8", errors="replace")
            dest = repo_root / "prompt-tests" / "journey.log"
            dest.write_text(journey_log_text, encoding="utf-8")

        last_step = detect_last_step(journey_log_text) if journey_log_text else "none"

        # Scoring: same blended approach as cursor for consistency
        overall_score = 10
        if not invariants["journey_log_used"]:
            overall_score -= 4
        if not invariants["interview_one_question_at_a_time"]:
            overall_score -= 1
        if not invariants["no_parent_directory_access"]:
            overall_score -= 1

        phase_weights = {
            "interview_filled": 1,
            "requirements_filled": 1,
            "registration_filled": 1,
            "cli_filled": 1,
            "build_filled": 2,
            "local_test_gate_filled": 2,
            "deploy_filled": 2,
            "end_state_filled": 1,
        }
        phase_score = sum(w for phase, w in phase_weights.items() if phases.get(phase))
        max_phase_score = sum(phase_weights.values())
        phase_scaled = (phase_score / max_phase_score) * 10 if max_phase_score else 0
        overall_score = round(overall_score * 0.4 + phase_scaled * 0.6, 1)
        overall_score = max(0, min(10, overall_score))

        report = {
            "engine": "codex",
            "scenario": scenario.get("name", "unknown"),
            "overall_score": overall_score,
            "turn_count": len(turns),
            "duration_seconds": duration,
            "stop_reason": stop_reason,
            "last_step_reached": last_step,
            "invariants": invariants,
            "phases": phases,
            "journey_log": journey_log_text,
            "transcript": [{"role": t.role, "message": t.message} for t in turns],
            "notable_failures": list(dict.fromkeys(notable_failures)),
        }

        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

