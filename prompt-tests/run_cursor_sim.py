#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
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


def _agent_path() -> Optional[str]:
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


def _create_session(api_url: str) -> str:
    """Call the analytics API to create a real session and return its ID."""
    url = f"{api_url.rstrip('/')}/api/v1/prompt/latest"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    session_id = data.get("session_id")
    if not session_id:
        raise RuntimeError("analytics API did not return a session_id")
    return session_id


def _poll_verification_code(
    api_url: str, session_id: str, *, timeout: int = 30, interval: int = 3
) -> Optional[str]:
    """Poll the test endpoint for the real verification code."""
    secret = os.environ.get("PROMPT_TEST_SECRET", "")
    if not secret:
        return None
    url = (
        f"{api_url.rstrip('/')}/api/v1/test/verification-code"
        f"?session_id={session_id}"
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers={"X-Test-Secret": secret})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    code = resp.read().decode().strip()
                    if code and code != "no pending code":
                        return code
        except urllib.error.HTTPError:
            pass
        time.sleep(interval)
    return None


def load_lane_prompt(repo_root: Path, api_url: str) -> Tuple[str, str]:
    """Load the prompt, create a real session, and return (prompt, session_id)."""
    prompt_path = repo_root / "scripts" / "default-prompt.txt"
    content = prompt_path.read_text(encoding="utf-8")
    session_id = _create_session(api_url)
    content = content.replace("{{API_URL}}", api_url.rstrip("/"))
    content = content.replace("{{SESSION_ID}}", session_id)
    return content, session_id


def load_scenario(repo_root: Path, scenario_path: Path) -> Dict[str, Any]:
    raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    terminal = raw["terminal"]
    cmd_outputs: Dict[str, str] = {}
    for cmd, rel in terminal["command_outputs"].items():
        p = (repo_root / rel).resolve()
        cmd_outputs[cmd] = p.read_text(encoding="utf-8")
    raw["terminal"] = {**terminal, "command_outputs": cmd_outputs}
    return raw


_TRANSIENT_PATTERNS = [
    "at capacity",
    "rate limit",
    "rate_limit",
    "overloaded",
    "503",
    "502",
    "500",
    "server error",
    "temporarily unavailable",
    "try again",
]

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 10  # seconds


def _is_transient(stdout: str, stderr: str) -> bool:
    combined = (stdout + "\n" + stderr).lower()
    return any(pat in combined for pat in _TRANSIENT_PATTERNS)


def run_agent_json(
    *,
    agent_path: str,
    workspace: Path,
    prompt: str,
    resume: Optional[str] = None,
    mode: Optional[str] = None,
    force: bool = False,
) -> Tuple[str, str]:
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

    last_error: Optional[RuntimeError] = None
    for attempt in range(_MAX_RETRIES + 1):
        p = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p.returncode == 0:
            break
        if _is_transient(p.stdout, p.stderr):
            last_error = RuntimeError(
                f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
            )
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"[retry] transient failure on attempt {attempt + 1}, retrying in {delay}s …",
                    flush=True,
                )
                time.sleep(delay)
                continue
        else:
            raise RuntimeError(
                f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
            )
    else:
        raise last_error  # type: ignore[misc]

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

    last_error: Optional[RuntimeError] = None
    for attempt in range(_MAX_RETRIES + 1):
        p = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if p.returncode == 0:
            break
        if _is_transient(p.stdout, p.stderr):
            last_error = RuntimeError(
                f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
            )
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"[retry] transient failure on attempt {attempt + 1}, retrying in {delay}s …",
                    flush=True,
                )
                time.sleep(delay)
                continue
        else:
            raise RuntimeError(
                f"agent failed (code={p.returncode})\nSTDERR:\n{p.stderr.strip()}\nSTDOUT:\n{p.stdout.strip()}"
            )
    else:
        raise last_error  # type: ignore[misc]

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
        "CRITICAL rules — never break these:\n"
        "- NEVER fabricate responses from external services (Discord, GitHub, email, etc.).\n"
        "- NEVER pretend you contacted someone or received a reply that did not happen.\n"
        "- If the lane agent asks you to post to Discord, escalate, or wait for external input,\n"
        "  reply with exactly: ESCALATED — waiting for external input.\n"
        "- Do NOT improvise fake external interactions to keep the conversation going.\n\n"
        "When asked for `lane --help`, respond with:\n"
        "Ran `lane --help`:\n"
        "<paste output>\n\n"
        f"- When asked for your email address, respond with: {email}\n"
        "- When asked for a verification code, respond with: 123456\n"
    )


def terminal_agent_next_input(
    *,
    agent_path: str,
    workspace: Path,
    terminal_session: str,
    lane_agent_message: str,
    command_outputs: Dict[str, str],
    api_url: str = "",
    session_id: str = "",
) -> str:
    msg_l = lane_agent_message.lower()
    if "lane --help" in msg_l or ("run" in msg_l and "--help" in msg_l and "lane" in msg_l):
        out = command_outputs.get("lane --help")
        if out:
            return f"Ran `lane --help`:\n\n{out}"

    # Intercept verification-code requests — poll backend for the real code
    if any(phrase in msg_l for phrase in ("verification code", "6-digit code", "digit code from")):
        if api_url and session_id:
            code = _poll_verification_code(api_url, session_id)
            if code:
                print("[verify] retrieved real verification code", flush=True)
                return code

    prompt = (
        "LaneAgent just said:\n"
        "<<<\n"
        f"{lane_agent_message}\n"
        ">>>\n\n"
        "What do you type next in the terminal? Reply with ONLY the next terminal message."
    )
    _, reply = run_agent_json(
        agent_path=agent_path,
        workspace=workspace,
        prompt=prompt,
        resume=terminal_session,
        mode="ask",
        force=False,
    )
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
    ap.add_argument("--api-url", default="https://analytics.lanelayer.com/")
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

    lane_prompt, created_session_id = load_lane_prompt(repo_root, args.api_url)
    print(f"[session] created session {created_session_id}", flush=True)
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

    with tempfile.TemporaryDirectory(prefix="lanelayer_prompt_sim_") as td:
        ws = Path(td)

        command_outputs = dict(scenario["terminal"]["command_outputs"])
        profile = dict(scenario["terminal"]["developer_profile"])

        terminal_boot = build_terminal_agent_bootstrap(profile, command_outputs)
        terminal_session, _ = run_agent_json(
            agent_path=agent_path,
            workspace=ws,
            prompt=terminal_boot,
            resume=None,
            mode="ask",
            force=False,
        )

        session_id, events = run_agent_stream_json(
            agent_path=agent_path, workspace=ws, prompt=lane_prompt, resume=None
        )
        for m in extract_assistant_messages(events):
            turns.append(Turn("LaneAgent", m))
            if looks_like_multiple_questions(m):
                invariants["interview_one_question_at_a_time"] = False
                notable_failures.append(
                    "LaneAgent asked multiple interview questions in one message"
                )
            if "parent director" in m.lower() or "scan" in m.lower() and "workspace" in m.lower():
                invariants["no_parent_directory_access"] = False
                notable_failures.append("LaneAgent mentioned scanning/parent directory access")

        max_turns = int(scenario.get("stop_after", {}).get("max_turns", 18))

        while len(turns) < max_turns:
            last_assistant = next(
                (t.message for t in reversed(turns) if t.role == "LaneAgent"), ""
            )

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
                agent_path=agent_path,
                workspace=ws,
                terminal_session=terminal_session,
                lane_agent_message=last_assistant,
                command_outputs=command_outputs,
                api_url=args.api_url,
                session_id=created_session_id,
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

            _, ev = run_agent_stream_json(
                agent_path=agent_path, workspace=ws, prompt=reply, resume=session_id
            )
            for m in extract_assistant_messages(ev):
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

        # Scoring
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
            "engine": "cursor",
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

