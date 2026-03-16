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


def _agent_path() -> Optional[str]:
    """Return path to Cursor 'agent' CLI, checking PATH then common install locations."""
    path = shutil.which("agent")
    if path:
        return path
    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / "agent",
        home / ".cursor" / "bin" / "agent",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def load_lane_prompt(repo_root: Path, api_url: str) -> str:
    prompt_path = repo_root / "scripts" / "default-prompt.txt"
    content = prompt_path.read_text(encoding="utf-8")
    return content.replace("{{API_URL}}", api_url.rstrip("/"))


def load_scenario(repo_root: Path, scenario_path: Path) -> Dict[str, Any]:
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    # Expand fixture file paths into string contents for command_outputs
    terminal = raw["terminal"]
    cmd_outputs: Dict[str, str] = {}
    for cmd, rel in terminal["command_outputs"].items():
        p = (repo_root / rel).resolve()
        cmd_outputs[cmd] = p.read_text(encoding="utf-8")
    raw["terminal"] = {**terminal, "command_outputs": cmd_outputs}
    return raw


def run_agent_json(
    *,
    agent_path: str,
    workspace: Path,
    prompt: str,
    resume: Optional[str] = None,
    mode: Optional[str] = None,
    force: bool = False,
) -> Tuple[str, str]:
    """
    Run Cursor 'agent' once in json output mode and return (session_id, assistant_text).
    """
    cmd = [
        agent_path,
        "--workspace",
        str(workspace),
        "--trust",
        "--print",
        "--output-format",
        "json",
    ]
    if force:
        cmd.append("--force")
    if mode is not None:
        cmd += ["--mode", mode]
    if resume is not None:
        cmd += ["--resume", resume]
    cmd.append(prompt)

    p = subprocess.run(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
        )

    try:
        obj = json.loads(p.stdout.strip())
    except Exception as e:
        raise RuntimeError(f"failed to parse agent json output: {e}\nRAW:\n{p.stdout}") from e

    session_id = obj.get("session_id")
    result = obj.get("result", "")
    if not session_id:
        raise RuntimeError("could not determine session_id from Cursor json output")
    if not isinstance(result, str):
        result = str(result)
    return session_id, result.strip()


def run_agent_stream_json(
    *,
    agent_path: str,
    workspace: Path,
    prompt: str,
    resume: Optional[str] = None,
    force: bool = True,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Run Cursor 'agent' once and return (session_id, events).

    We rely on Cursor CLI stream-json format so we can capture each assistant message.
    """
    cmd = [
        agent_path,
        "--workspace",
        str(workspace),
        "--trust",
        "--print",
        "--output-format",
        "stream-json",
    ]
    if force:
        cmd.append("--force")
    if resume is not None:
        cmd += ["--resume", resume]
    cmd.append(prompt)

    p = subprocess.run(
        cmd,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
        )

    events: List[Dict[str, Any]] = []
    session_id: Optional[str] = None
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(evt)
        if evt.get("type") == "system" and evt.get("subtype") == "init":
            session_id = evt.get("session_id")

    if not session_id:
        # Fallback: try result event
        for evt in reversed(events):
            if evt.get("type") == "result" and evt.get("session_id"):
                session_id = evt["session_id"]
                break
    if not session_id:
        raise RuntimeError("could not determine session_id from Cursor stream-json output")

    return session_id, events


def extract_assistant_messages(events: List[Dict[str, Any]]) -> List[str]:
    msgs: List[str] = []
    for evt in events:
        if evt.get("type") != "assistant":
            continue
        content = evt.get("message", {}).get("content", [])
        texts = []
        for part in content:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
        msg = "".join(texts).strip()
        if msg:
            msgs.append(msg)
    return msgs


def looks_like_multiple_questions(text: str) -> bool:
    # Heuristic: multiple numbered questions or multiple distinct known questions.
    numbered = len(re.findall(r"(?m)^\s*\d+\.\s+", text))
    if numbered >= 2:
        return True
    matched = sum(1 for q in INTERVIEW_QUESTIONS if q.lower() in text.lower())
    return matched >= 2


def build_terminal_agent_bootstrap(profile: Dict[str, str], command_outputs: Dict[str, str]) -> str:
    """
    Build the initial instruction for the TerminalAgent.
    TerminalAgent plays the developer in the terminal and must respond with the single next terminal message only.
    """
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
        f"{outputs_preview}\n\n"
        "CRITICAL rules — never break these:\n"
        "- NEVER fabricate responses from external services (Discord, GitHub, email, etc.).\n"
        "- NEVER pretend you contacted someone or received a reply that did not happen.\n"
        "- If the lane agent asks you to post to Discord, escalate, or wait for external input,\n"
        "  reply with exactly: ESCALATED — waiting for external input.\n"
        "- Do NOT improvise fake external interactions to keep the conversation going.\n\n"
        "When asked for `lane --help`, respond with:\n"
        "Ran `lane --help`:\n"
        "<paste output>\n"
    )


def terminal_agent_next_input(
    *,
    agent_path: str,
    workspace: Path,
    terminal_session: str,
    lane_agent_message: str,
    command_outputs: Dict[str, str],
) -> str:
    msg_l = lane_agent_message.lower()
    # Hard override for known commands to keep determinism.
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
    _, reply = run_agent_json(agent_path=agent_path, workspace=workspace, prompt=prompt, resume=terminal_session, mode="ask", force=False)
    return reply


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


def check_journey_log_progress(workspace: Path) -> Tuple[Dict[str, bool], List[str]]:
    """Check whether each journey.log phase has real content (not just 'unknown' placeholders)."""
    phases: Dict[str, bool] = {
        "interview_filled": False,
        "requirements_filled": False,
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
        """Extract text between header and the next '###' header (or end of file)."""
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-url", default="https://lanelayer-analytics.fly.dev")
    ap.add_argument(
        "--scenario",
        default=str(Path(__file__).parent / "scenarios" / "basic.json"),
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    agent_path = _agent_path()
    if agent_path is None:
        raise SystemExit(
            "error: Cursor CLI 'agent' not found. Install with: curl -fsS https://cursor.com/install | bash\n"
            "Then ensure ~/.local/bin is on your PATH, or run from a shell where 'agent' works."
        )

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

    with tempfile.TemporaryDirectory(prefix="lanelayer_prompt_sim_") as td:
        ws = Path(td)

        command_outputs = dict(scenario["terminal"]["command_outputs"])
        profile = dict(scenario["terminal"]["developer_profile"])

        # Boot TerminalAgent session.
        terminal_boot = build_terminal_agent_bootstrap(profile, command_outputs)
        terminal_session, _ = run_agent_json(agent_path=agent_path, workspace=ws, prompt=terminal_boot, resume=None, mode="ask", force=False)

        # Turn 0: feed the lane prompt as the initial instruction (LaneAgent session).
        session_id, events = run_agent_stream_json(agent_path=agent_path, workspace=ws, prompt=lane_prompt, resume=None)
        for m in extract_assistant_messages(events):
            turns.append(Turn("LaneAgent", m))
            if looks_like_multiple_questions(m):
                invariants["interview_one_question_at_a_time"] = False
                notable_failures.append("LaneAgent asked multiple interview questions in one message")
            if "parent director" in m.lower() or "scan" in m.lower() and "workspace" in m.lower():
                invariants["no_parent_directory_access"] = False
                notable_failures.append("LaneAgent mentioned scanning/parent directory access")

        max_turns = int(scenario.get("stop_after", {}).get("max_turns", 18))
        stop_early = False
        # Loop: LaneAgent <-> TerminalAgent.
        while len(turns) < max_turns and not stop_early:
            last_assistant = next((t.message for t in reversed(turns) if t.role == "LaneAgent"), "")

            last_l = last_assistant.lower()
            if any(phrase in last_l for phrase in (
                "standing by",
                "just let me know",
                "just drop a message",
                "waiting for",
                "once you get the",
                "when the fix is live",
            )):
                notable_failures.append("LaneAgent reached a blocked/waiting state — ending simulation")
                break

            reply = terminal_agent_next_input(
                agent_path=agent_path,
                workspace=ws,
                terminal_session=terminal_session,
                lane_agent_message=last_assistant,
                command_outputs=command_outputs,
            )
            if not reply.strip():
                break

            if "ESCALATED" in reply.upper() and "waiting for external input" in reply.lower():
                turns.append(Turn("Terminal", reply))
                notable_failures.append("TerminalAgent escalated — simulation ended (no external service available)")
                break

            turns.append(Turn("Terminal", reply))

            _, ev = run_agent_stream_json(agent_path=agent_path, workspace=ws, prompt=reply, resume=session_id)
            for m in extract_assistant_messages(ev):
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

        phases, phase_failures = check_journey_log_progress(ws)
        notable_failures.extend(phase_failures)

        # Copy journey.log out of the temporary workspace so it can be inspected after the run.
        jl_path = ws / "journey.log"
        if jl_path.exists():
            dest = repo_root / "prompt-tests" / "journey.log"
            dest.write_text(jl_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

        # --- Scoring ---
        # Invariant penalties (max -6)
        overall_score = 10
        if not invariants["journey_log_used"]:
            overall_score -= 4
        if not invariants["interview_one_question_at_a_time"]:
            overall_score -= 1
        if not invariants["no_parent_directory_access"]:
            overall_score -= 1

        # Phase-progress penalties: each incomplete phase costs points.
        phase_weights = {
            "interview_filled": 1,
            "requirements_filled": 1,
            "cli_filled": 1,
            "build_filled": 2,
            "local_test_gate_filled": 2,
            "deploy_filled": 2,
            "end_state_filled": 1,
        }
        phase_score = sum(w for phase, w in phase_weights.items() if phases.get(phase))
        max_phase_score = sum(phase_weights.values())
        # Scale phase progress into 0-10 and blend: 40% invariants, 60% phase progress.
        phase_scaled = (phase_score / max_phase_score) * 10 if max_phase_score else 0
        overall_score = round(overall_score * 0.4 + phase_scaled * 0.6, 1)
        overall_score = max(0, min(10, overall_score))

        report = {
            "engine": "cursor",
            "scenario": scenario.get("name", "unknown"),
            "overall_score": overall_score,
            "overall_rationale": (
                "Score = 40% invariant compliance + 60% journey phase progress. "
                "Phases stuck at 'unknown' are penalized."
            ),
            "invariants": invariants,
            "phases": phases,
            "transcript": [{"role": t.role, "message": t.message} for t in turns],
            "notable_failures": list(dict.fromkeys(notable_failures)),
        }

        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

