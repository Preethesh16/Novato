"""Safety, privacy, memory, and orchestration tests for the Groq agent."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from rich.console import Console

from novato import config as cfgmod
from novato.agent import AgentSession
from novato.agent_curriculum import BEHAVIOR_CURRICULUM, NOVATO_CAPABILITIES, build_agent_prompt
from novato.agent_memory import MemoryStore, memory_path
from novato.agent_tools import ToolRegistry, validate_action_argv
from novato.agent_types import ActionProposal, AgentMessage, ToolResult
from novato.detector import SystemInfo
from novato.executor import ExecResult, execute_argv
from novato.intent import IntentResolver
from novato.main import App
from novato.presenter import Presenter
from novato.privacy import redact, redact_text
from novato.backends.groq_backend import GroqBackend


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    return tmp_path


def _system():
    return SystemInfo(
        distro_id="arch", distro_name="Arch Linux", distro_version="rolling",
        package_manager="pacman", install_cmd="sudo pacman -S",
        search_cmd="pacman -Ss", supports_aur=True, aur_helper="yay",
        shell="zsh", supported=True,
    )


class _Backend:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def agent_completion(self, messages, tools):
        self.requests.append(list(messages))
        return next(self.replies, None)


class _Registry:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def groq_tools(self):
        return []

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        if self.results:
            return self.results.pop(0)
        return ToolResult(name, True, {"value": "verified"}, timestamp="now")

    def apply_config_edit(self, proposal, dry_run=False):
        return ToolResult("propose_config_edit", True, {"path": proposal.path})


def _ui(answers=()):
    stream = StringIO()
    values = iter(answers)
    return Presenter(
        console=Console(file=stream, no_color=True, width=120),
        input_fn=lambda _prompt: next(values, "n"),
    ), stream


def _call(call_id="c1", name="get_system_summary", arguments="{}"):
    return AgentMessage("assistant", tool_calls=[{
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": arguments},
    }])


def test_agent_single_tool_then_final_and_consent_once(isolated_home):
    backend = _Backend([_call(), AgentMessage("assistant", "You are on Arch Linux.")])
    registry = _Registry([ToolResult("get_system_summary", True, {"distro": "Arch"})])
    ui, stream = _ui(["y"])
    session = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry)

    outcome = session.ask("which Linux am I using?")

    assert outcome.handled
    assert registry.calls == [("get_system_summary", {})]
    assert "You are on Arch Linux" in stream.getvalue()
    outbound = backend.requests[1]
    assert any(message.get("role") == "tool" for message in outbound)


def test_read_only_probe_needs_privacy_consent_but_no_action_confirmation(isolated_home):
    prompts = []
    ui = Presenter(
        console=Console(file=StringIO(), no_color=True),
        input_fn=lambda prompt: prompts.append(prompt) or "y",
    )
    backend = _Backend([_call(), AgentMessage("assistant", "Inspected.")])
    session = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=_Registry())
    assert session.ask("inspect").handled
    assert len(prompts) == 1
    assert "Send this redacted evidence" in prompts[0]
    assert not any("Confirm?" in prompt for prompt in prompts)


def test_agent_multi_tool_loop_preserves_results(isolated_home):
    backend = _Backend([
        _call("c1", "get_system_summary"),
        _call("c2", "inspect_kernels"),
        AgentMessage("assistant", "Stable is running and LTS is available."),
    ])
    registry = _Registry([
        ToolResult("get_system_summary", True, {"distro": "Arch"}),
        ToolResult("inspect_kernels", True, {
            "running_kernel": "7.1.7-arch1-1", "installed_images": ["vmlinuz-linux-lts"],
        }),
    ])
    ui, _ = _ui(["y"])
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry).ask("check my kernels")
    assert outcome.handled
    assert [name for name, _ in registry.calls] == ["get_system_summary", "inspect_kernels"]


def test_consent_decline_does_not_send_tool_result(isolated_home):
    backend = _Backend([_call(), AgentMessage("assistant", "should not happen")])
    registry = _Registry([ToolResult("get_system_summary", True, {"hostname": "secret-host"})])
    ui, _ = _ui(["n"])
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry).ask("inspect this system")
    assert not outcome.handled
    assert len(backend.requests) == 1


def test_malformed_tool_calls_stop_after_one_retry(isolated_home):
    backend = _Backend([
        _call("c1", arguments="{bad"), _call("c2", arguments="still bad"),
    ])
    ui, _ = _ui(["y"])
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=_Registry()).ask("inspect")
    assert outcome.handled and outcome.exit_code == 1


def test_duplicate_tool_call_id_never_executes_twice(isolated_home):
    backend = _Backend([
        _call("same"), _call("same"), AgentMessage("assistant", "done"),
    ])
    registry = _Registry()
    ui, _ = _ui(["y"])
    AgentSession(backend=backend, system=_system(), presenter=ui,
                 registry=registry).ask("inspect")
    assert len(registry.calls) == 1


def test_api_failure_requests_deterministic_fallback(isolated_home):
    ui, _ = _ui()
    outcome = AgentSession(backend=_Backend([]), system=_system(), presenter=ui,
                           registry=_Registry()).ask("help")
    assert not outcome.handled


def test_agent_stops_at_eight_tool_steps(isolated_home):
    backend = _Backend([_call(f"c{i}") for i in range(1, 10)])
    registry = _Registry()
    ui, _ = _ui(["y"])
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry).ask("keep inspecting forever")
    assert outcome.handled and outcome.exit_code == 1
    assert len(registry.calls) == 8


def test_mutation_requires_confirmation_and_decline_executes_nothing(
    isolated_home, monkeypatch,
):
    proposal = ActionProposal(
        "a1", "update packages", argv=("sudo", "pacman", "-Syu"),
        preview="sudo pacman -Syu", expected_result="system updated",
        verification_tool="inspect_packages", verification_args={"pending": True},
    )
    backend = _Backend([
        _call("inspect", "inspect_packages", '{"pending":true}'),
        _call("propose", "propose_action"), AgentMessage("assistant", "declined"),
    ])
    registry = _Registry([
        ToolResult("inspect_packages", True, {"pending_updates": "x"}), proposal,
    ])
    executed = []
    monkeypatch.setattr("novato.agent.execute_argv", lambda *a, **k: executed.append(a))
    ui, _ = _ui(["y", "n"])  # consent to evidence, then decline the action
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry).ask("update")
    assert outcome.handled
    assert executed == []


def test_agent_requires_inspection_before_mutation(isolated_home, monkeypatch):
    proposal = ActionProposal(
        "a1", "update packages", argv=("sudo", "pacman", "-Syu"),
        expected_result="updated", verification_tool="inspect_packages",
    )
    backend = _Backend([
        _call("propose", "propose_action"), AgentMessage("assistant", "I must inspect first."),
    ])
    registry = _Registry([proposal])
    executed = []
    monkeypatch.setattr("novato.agent.execute_argv", lambda *a, **k: executed.append(a))
    ui, _ = _ui(["y"])
    outcome = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry).ask("update")
    assert outcome.handled
    assert executed == []


def test_verified_action_executes_once_and_is_remembered(isolated_home, monkeypatch):
    proposal = ActionProposal(
        "a1", "update packages", argv=("sudo", "pacman", "-Syu"),
        preview="sudo pacman -Syu", expected_result="no pending official updates",
        verification_tool="inspect_packages", verification_args={"pending": True},
    )
    backend = _Backend([
        _call("inspect", "inspect_packages", '{"pending":true}'),
        _call("propose", "propose_action"), AgentMessage("assistant", "Verified."),
    ])
    registry = _Registry([
        ToolResult("inspect_packages", True, {"pending_updates": "x"}),
        proposal, ToolResult("inspect_packages", True, {"pending_updates": ""}),
    ])
    calls = []
    monkeypatch.setattr(
        "novato.agent.execute_argv",
        lambda argv, **kwargs: calls.append(tuple(argv)) or ExecResult(
            "sudo pacman -Syu", 0, executed=True, elapsed_seconds=2.5,
        ),
    )
    ui, _ = _ui(["y", "y"])  # consent to evidence, then confirm action
    session = AgentSession(backend=backend, system=_system(), presenter=ui,
                           registry=registry)
    assert session.ask("update safely").handled
    assert calls == [("sudo", "pacman", "-Syu")]
    facts = MemoryStore().load()
    assert len(facts) == 1
    assert facts[0].action_outcome == "completed and verified"
    assert "no pending" in facts[0].summary
    assert not any("transcript" in line.lower() for line in memory_path().read_text().splitlines())


def test_interrupted_action_is_not_remembered(isolated_home, monkeypatch):
    proposal = ActionProposal(
        "a1", "update packages", argv=("sudo", "pacman", "-Syu"),
        expected_result="updated", verification_tool="inspect_packages",
    )
    backend = _Backend([
        _call("inspect", "inspect_packages", '{"pending":true}'),
        _call("propose", "propose_action"), AgentMessage("assistant", "cancelled"),
    ])
    registry = _Registry([
        ToolResult("inspect_packages", True, {"pending_updates": "x"}), proposal,
    ])
    monkeypatch.setattr(
        "novato.agent.execute_argv",
        lambda *a, **k: ExecResult("sudo pacman -Syu", 130, executed=True,
                                   reason="cancelled by user"),
    )
    ui, _ = _ui(["y", "y"])
    AgentSession(backend=backend, system=_system(), presenter=ui,
                 registry=registry).ask("update")
    assert MemoryStore().load() == []


def test_memory_forget_and_permissions(isolated_home):
    from novato.agent_types import MemoryFact

    store = MemoryStore()
    store.append(MemoryFact("one", "now", "preference", "tone", "concise",
                            "user", "confirmed"))
    store.append(MemoryFact("two", "now", "system", "kernel", "stable active",
                            "inspect_kernels", "verified"))
    assert memory_path().stat().st_mode & 0o777 == 0o600
    assert store.forget("one") == 1
    assert [fact.id for fact in store.load()] == ["two"]
    assert store.forget("all") == 1


def test_privacy_redacts_secrets_identity_and_paths(monkeypatch):
    monkeypatch.setenv("USER", "alice")
    text = "alice on laptop used token=abc123 at /home/alice/private API_KEY=qwerty"
    cleaned = redact_text(text)
    assert "alice" not in cleaned
    assert "abc123" not in cleaned
    assert "qwerty" not in cleaned
    assert "/home/alice" not in cleaned
    nested = redact({"authorization": "Bearer wow", "output": text})
    assert nested["authorization"] == "<REDACTED>"


def test_agent_action_policy_blocks_shell_and_arbitrary_programs():
    assert validate_action_argv(["sudo", "pacman", "-S", "firefox"])[0]
    assert not validate_action_argv(["sudo", "pacman", "-S", "x;reboot"])[0]
    assert not validate_action_argv(["curl", "https://example.com/script"])[0]
    assert not validate_action_argv(["sudo", "pacman", "-S", "x", "--noconfirm"])[0]
    assert not validate_action_argv(["sudo", "/tmp/pacman", "-S", "firefox"])[0]
    assert not validate_action_argv(["sudo", "apt", "install", "./untrusted.deb"])[0]
    assert not validate_action_argv(["sudo", "grub-mkconfig", "-o", "/tmp/grub.cfg"])[0]
    assert execute_argv(["echo", "should-not-run"], dry_run=True).blocked


def test_arch_vscode_update_resolves_real_aur_package(monkeypatch):
    monkeypatch.setattr(
        "novato.agent_tools.installed.installed_versions",
        lambda _pm: {"visual-studio-code-bin": "1.131.0-1", "firefox": "140.0-1"},
    )
    monkeypatch.setattr(
        "novato.agent_tools.installed.foreign_packages",
        lambda: {"visual-studio-code-bin"},
    )
    registry = ToolRegistry(_system())

    inspection = registry.execute("inspect_packages", {"package": "vscode"})
    assert inspection.ok
    assert inspection.facts["package_manager"] == "pacman"
    assert inspection.facts["matches"] == [{
        "name": "visual-studio-code-bin", "version": "1.131.0-1", "origin": "aur",
    }]

    proposal = registry.execute(
        "propose_package_action", {"action": "update", "package": "vscode"},
    )
    assert isinstance(proposal, ActionProposal)
    assert proposal.operation == "package_action"
    assert proposal.argv == ("yay", "-S", "visual-studio-code-bin")
    assert proposal.verification_args == {"package": "visual-studio-code-bin"}


def test_generic_model_package_command_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "novato.agent_tools.installed.installed_versions", lambda _pm: {},
    )
    monkeypatch.setattr(
        "novato.agent_tools.installed.foreign_packages", lambda: set(),
    )
    result = ToolRegistry(_system()).execute("propose_action", {
        "purpose": "Install VSCode", "argv": ["sudo", "apt", "install", "code"],
        "expected_result": "installed", "verification_tool": "inspect_packages",
        "verification_args": {"package": "code"},
    })
    assert isinstance(result, ToolResult)
    assert not result.ok
    assert "propose_package_action" in result.error


def test_package_action_requires_package_inspection(isolated_home, monkeypatch):
    proposal = ActionProposal(
        "pkg1", "Update visual-studio-code-bin using pacman",
        operation="package_action", argv=("yay", "-S", "visual-studio-code-bin"),
        expected_result="version rechecked", verification_tool="inspect_packages",
        verification_args={"package": "visual-studio-code-bin"},
    )
    backend = _Backend([
        _call("system", "get_system_summary"),
        _call("proposal", "propose_package_action"),
        AgentMessage("assistant", "I need package evidence first."),
    ])
    registry = _Registry([
        ToolResult("get_system_summary", True, {"package_manager": "pacman"}), proposal,
    ])
    executed = []
    monkeypatch.setattr("novato.agent.execute_argv", lambda *a, **k: executed.append(a))
    ui, _ = _ui(["y"])
    assert AgentSession(backend=backend, system=_system(), presenter=ui,
                        registry=registry).ask("update vscode").handled
    assert executed == []


def test_read_file_tool_blocks_secrets_and_outside_paths(tmp_path):
    registry = ToolRegistry(_system())
    denied = registry.execute("read_config_file", {"path": "/etc/shadow"})
    assert not denied.ok
    outside = tmp_path / "private.txt"
    outside.write_text("secret")
    denied = registry.execute("read_config_file", {"path": str(outside)})
    assert not denied.ok


def test_config_schema_migrates_without_losing_settings(isolated_home):
    path = cfgmod.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "mode": "online", "explain": True,
                                "groq_api_key": "keep-me"}))
    config = cfgmod.load_config()
    assert config.version == 2
    assert config.mode == "online" and config.explain
    assert config.groq_api_key == "keep-me"


def test_chat_supports_new_status_and_exit(isolated_home, monkeypatch):
    answers = iter(["/new", "/status", "/exit"])
    ui = Presenter(
        console=Console(file=StringIO(), no_color=True),
        input_fn=lambda _prompt: next(answers),
    )
    app = App(system=_system(), config=cfgmod.Config(mode="basic"),
              presenter=ui, resolver=IntentResolver())
    backend = _Backend([])
    monkeypatch.setattr(app, "_online_backend", lambda: backend)
    assert app.chat() == 0
    assert backend.requests == []


def test_groq_backend_parses_structured_tool_call():
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "inspect_kernels", "arguments": "{}"},
                }],
            }}]}

    class Session:
        payload = None

        def post(self, _url, json=None, **_kwargs):
            self.payload = json
            return Response()

    transport = Session()
    backend = GroqBackend("fake", session=transport)
    message = backend.agent_completion(
        [{"role": "user", "content": "check kernels"}],
        [{"type": "function", "function": {"name": "inspect_kernels"}}],
    )
    assert message.tool_calls[0]["function"]["name"] == "inspect_kernels"
    assert transport.payload["tool_choice"] == "auto"
    assert transport.payload["parallel_tool_calls"] is False


def test_agent_curriculum_preserves_previous_novato_behavior():
    prompt = build_agent_prompt("core safety")
    for required in (
        "propose_package_action", "never choose apt", "verified memory",
        "Never start a second copy", "Arch is rolling release", "/clean storage",
        "/mistake", "/explain", "Report success only after local verification",
    ):
        assert required in prompt
    assert NOVATO_CAPABILITIES in prompt
    assert BEHAVIOR_CURRICULUM in prompt
