# SPDX-License-Identifier: GPL-3.0-or-later
"""Registered, bounded local tools exposed to the Groq agent."""

from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import platform
import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from . import installed, logger, sysinfo
from .agent_types import ActionProposal, ToolResult, ToolRisk, ToolSpec
from .detector import SystemInfo
from .searcher import search_candidates

_MAX_OUTPUT = 12_000
_TIMEOUT = 20
_META = re.compile(r"[;&|`$<>\n\r]")
_DENIED_FILES = {
    "/etc/shadow", "/etc/gshadow", "/etc/passwd", "/etc/group",
    "/etc/sudoers", "/etc/security/opasswd",
}
_DENIED_PATH_PARTS = frozenset({
    ".ssh", ".gnupg", ".aws", ".kube", "private", "private-keys-v1.d",
    "system-connections", "wireguard",
})

# Agent-generated commands are intentionally much narrower than Novato's
# general executor. The subcommand is checked as well as the executable.
_CHANGE_POLICIES: dict[str, tuple[str, ...]] = {
    "pacman": ("-S", "-R", "-Rs", "-Rns", "-Syu", "-Sc"),
    "yay": ("-S", "-R", "-Rs", "-Rns", "-Syu", "-Sc"),
    "paru": ("-S", "-R", "-Rs", "-Rns", "-Syu", "-Sc"),
    "apt": ("install", "remove", "purge", "upgrade", "update", "autoremove"),
    "apt-get": ("install", "remove", "purge", "upgrade", "update", "autoremove"),
    "dnf": ("install", "remove", "upgrade", "update"),
    "zypper": ("install", "remove", "update", "refresh"),
    "systemctl": ("start", "stop", "restart", "enable", "disable", "mask", "unmask"),
    "grub-mkconfig": ("-o",),
    "update-grub": (),
    "mkinitcpio": ("-P", "-p"),
    "update-initramfs": ("-u",),
    "paccache": ("-r", "-rk1", "-ruk0"),
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _bounded(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_OUTPUT:
        return text, False
    return text[:_MAX_OUTPUT] + "\n<OUTPUT TRUNCATED>", True


def _run(argv: list[str], timeout: int = _TIMEOUT) -> tuple[int, str, bool]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False,
        )
        text, truncated = _bounded((proc.stdout + proc.stderr).strip())
        return proc.returncode, text, truncated
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        text, truncated = _bounded(partial)
        return 124, text or "probe timed out", truncated
    except (OSError, ValueError) as exc:
        return 127, str(exc), False


def validate_action_argv(argv: list[str] | tuple[str, ...]) -> tuple[bool, str]:
    """Validate a model-proposed mutation against executable/subcommand policy."""
    args = [str(item) for item in argv]
    if not args:
        return False, "empty command"
    if any(not arg or _META.search(arg) for arg in args):
        return False, "shell syntax and empty arguments are not allowed"
    if any(arg in ("-y", "--yes", "--noconfirm", "--assumeyes", "--non-interactive")
           for arg in args):
        return False, "automatic confirmation flags are forbidden"
    index = 1 if args[0] in ("sudo", "doas") else 0
    if index >= len(args):
        return False, "missing executable"
    program = Path(args[index]).name
    if args[index] != program:
        return False, "agent executables must use an approved bare program name"
    if program not in _CHANGE_POLICIES:
        return False, f"'{program}' is not an approved agent action"
    allowed = _CHANGE_POLICIES[program]
    remaining = args[index + 1:]
    if allowed and not remaining:
        return False, f"'{program}' needs an approved subcommand"
    if allowed and not any(
        remaining[0] == choice or remaining[0].startswith(choice + "=") for choice in allowed
    ):
        return False, f"'{remaining[0]}' is not an approved {program} operation"
    if not allowed and remaining:
        return False, f"'{program}' does not accept agent-supplied arguments"
    if any(item.startswith("-") for item in remaining[1:]):
        return False, "extra command flags are not allowed in agent actions"
    if program == "grub-mkconfig" and remaining != ["-o", "/boot/grub/grub.cfg"]:
        return False, "grub-mkconfig may only regenerate /boot/grub/grub.cfg"
    if program == "systemctl" and any(
        not re.fullmatch(r"[A-Za-z0-9@_.:-]{1,100}", target)
        for target in remaining[1:]
    ):
        return False, "invalid systemd unit name"
    if program in ("pacman", "yay", "paru", "apt", "apt-get", "dnf", "zypper"):
        if any(not re.fullmatch(r"[A-Za-z0-9@.+_:=~-]{1,150}", target)
               for target in remaining[1:]):
            return False, "package targets must be repository package names"
    return True, ""


class ToolRegistry:
    """Maps model-visible schemas to fixed local implementations."""

    def __init__(self, system: SystemInfo) -> None:
        self.system = system

    @property
    def specs(self) -> list[ToolSpec]:
        obj = {"type": "object", "properties": {}, "additionalProperties": False}
        return [
            ToolSpec("get_system_summary", "Get verified Linux distribution, shell, package manager and architecture.", obj),
            ToolSpec("inspect_kernels", "Inspect the running kernel, installed kernel images and bootloader configuration hints.", obj),
            ToolSpec("inspect_storage", "Inspect mounted filesystem capacity and largest home folders.", {
                "type": "object", "properties": {"include_largest": {"type": "boolean"}},
                "additionalProperties": False,
            }),
            ToolSpec("inspect_packages", "Inspect installed packages, pending updates, or one named package.", {
                "type": "object", "properties": {
                    "package": {"type": "string"}, "pending": {"type": "boolean"},
                }, "additionalProperties": False,
            }),
            ToolSpec("search_packages", "Search real configured repositories for software matching candidate names.", {
                "type": "object", "properties": {
                    "candidates": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                }, "required": ["candidates"], "additionalProperties": False,
            }),
            ToolSpec("inspect_service", "Inspect a systemd service and recent logs.", {
                "type": "object", "properties": {"name": {"type": "string", "maxLength": 100}},
                "required": ["name"], "additionalProperties": False,
            }),
            ToolSpec("inspect_network", "Inspect local interfaces, routes and DNS status without changing them.", obj),
            ToolSpec("inspect_battery", "Inspect batteries and the active platform power profile.", obj),
            ToolSpec("inspect_processes", "Inspect top processes or the process listening on a port.", {
                "type": "object", "properties": {"port": {"type": "integer", "minimum": 1, "maximum": 65535}},
                "additionalProperties": False,
            }),
            ToolSpec("read_config_file", "Read a bounded non-secret file under /etc, /boot, or the current project.", {
                "type": "object", "properties": {"path": {"type": "string", "maxLength": 500}},
                "required": ["path"], "additionalProperties": False,
            }),
            ToolSpec("propose_action", "Propose one state-changing argv command. It is never run without user confirmation.", {
                "type": "object", "properties": {
                    "purpose": {"type": "string", "maxLength": 300},
                    "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 20},
                    "expected_result": {"type": "string", "maxLength": 300},
                    "verification_tool": {"type": "string"},
                    "verification_args": {"type": "object"},
                }, "required": ["purpose", "argv", "expected_result", "verification_tool"],
                "additionalProperties": False,
            }, ToolRisk.CHANGE),
            ToolSpec("propose_config_edit", "Propose changing one KEY=value setting in an existing /etc config file with diff and backup.", {
                "type": "object", "properties": {
                    "purpose": {"type": "string", "maxLength": 300},
                    "path": {"type": "string", "maxLength": 500},
                    "key": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_.-]*$"},
                    "value": {"type": "string", "maxLength": 1000},
                    "expected_result": {"type": "string", "maxLength": 300},
                    "verification_tool": {"type": "string"},
                    "verification_args": {"type": "object"},
                }, "required": ["purpose", "path", "key", "value", "expected_result", "verification_tool"],
                "additionalProperties": False,
            }, ToolRisk.CHANGE),
        ]

    def groq_tools(self) -> list[dict[str, Any]]:
        return [spec.as_groq_tool() for spec in self.specs]

    def risk_for(self, name: str) -> ToolRisk:
        return next((spec.risk for spec in self.specs if spec.name == name), ToolRisk.BLOCKED)

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult | ActionProposal:
        if self.risk_for(name) is ToolRisk.BLOCKED:
            return ToolResult(name, False, timestamp=_now(), error="unknown tool")
        if name == "propose_action":
            return self._propose_action(arguments)
        if name == "propose_config_edit":
            return self._propose_config_edit(arguments)
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return ToolResult(name, False, timestamp=_now(), error="tool unavailable")
        try:
            return handler(arguments)
        except (OSError, TypeError, ValueError) as exc:
            return ToolResult(name, False, timestamp=_now(), error=str(exc))

    def _get_system_summary(self, _args: dict[str, Any]) -> ToolResult:
        facts = self.system.as_dict()
        facts.update({"architecture": platform.machine(), "python": platform.python_version()})
        return ToolResult("get_system_summary", True, facts, timestamp=_now())

    def _inspect_kernels(self, _args: dict[str, Any]) -> ToolResult:
        rc, running, trunc1 = _run(["uname", "-r"])
        images = sorted(str(path) for path in Path("/boot").glob("vmlinuz*"))
        configs = {}
        for raw in ("/etc/default/grub", "/etc/kernel/cmdline"):
            path = Path(raw)
            if path.is_file():
                try:
                    lines = [line.strip() for line in path.read_text(errors="replace").splitlines()
                             if line.strip() and not line.lstrip().startswith("#")]
                    configs[raw] = lines[:30]
                except OSError:
                    pass
        return ToolResult("inspect_kernels", rc == 0, {
            "running_kernel": running.strip(), "installed_images": images,
            "boot_configuration": configs,
        }, exit_status=rc, timestamp=_now(), truncated=trunc1)

    def _inspect_storage(self, args: dict[str, Any]) -> ToolResult:
        mounts = [vars(item) for item in sysinfo.disk_mounts()]
        largest = []
        if args.get("include_largest", True):
            largest = [vars(item) for item in sysinfo.largest_dirs("~", limit=8)]
        return ToolResult("inspect_storage", True, {"mounts": mounts, "largest": largest}, timestamp=_now())

    def _inspect_packages(self, args: dict[str, Any]) -> ToolResult:
        package = str(args.get("package", "")).strip()
        if package:
            info = installed.get_info(package, self.system.package_manager)
            return ToolResult("inspect_packages", True, {
                "package": package, "installed": info is not None,
                "version": info.version if info else "", "origin": info.origin if info else "",
            }, timestamp=_now())
        if not args.get("pending", False):
            versions = installed.installed_versions(self.system.package_manager)
            return ToolResult("inspect_packages", True, {
                "installed_count": len(versions), "sample": dict(list(versions.items())[:30]),
            }, timestamp=_now(), truncated=len(versions) > 30)
        commands = {
            "pacman": ["pacman", "-Qu"], "apt": ["apt", "list", "--upgradable"],
            "dnf": ["dnf", "check-update"], "zypper": ["zypper", "list-updates"],
        }
        argv = commands.get(self.system.package_manager)
        if argv is None:
            return ToolResult("inspect_packages", False, timestamp=_now(), error="unsupported package manager")
        rc, output, truncated = _run(argv)
        # dnf uses 100 to mean updates are available.
        ok = rc in (0, 100)
        return ToolResult("inspect_packages", ok, {"pending_updates": output},
                          exit_status=rc, timestamp=_now(), truncated=truncated)

    def _search_packages(self, args: dict[str, Any]) -> ToolResult:
        candidates = [str(item)[:80] for item in args.get("candidates", [])[:6]]
        rows = search_candidates(candidates, self.system.package_manager,
                                 include_aur=self.system.supports_aur)
        facts = [{"name": row.name, "description": row.description[:300],
                  "repo": row.repo, "source": row.source} for row in rows[:12]]
        return ToolResult("search_packages", True, {"results": facts}, timestamp=_now(),
                          truncated=len(rows) > 12)

    def _inspect_service(self, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9@_.:-]{1,100}", name):
            raise ValueError("invalid service name")
        rc1, status, trunc1 = _run(["systemctl", "status", name, "--no-pager", "--lines=25"])
        rc2, logs, trunc2 = _run(["journalctl", "-u", name, "-n", "30", "--no-pager"])
        return ToolResult("inspect_service", rc1 in (0, 3), {
            "service": name, "status": status, "recent_logs": logs,
        }, exit_status=rc1, timestamp=_now(), truncated=trunc1 or trunc2 or rc2 not in (0,))

    def _inspect_network(self, _args: dict[str, Any]) -> ToolResult:
        facts = {}
        truncated = False
        for label, argv in (("interfaces", ["ip", "-brief", "address"]),
                            ("routes", ["ip", "route"]),
                            ("dns", ["resolvectl", "status"])):
            rc, output, cut = _run(argv, timeout=8)
            facts[label] = {"exit_status": rc, "output": output}
            truncated |= cut
        return ToolResult("inspect_network", True, facts, timestamp=_now(), truncated=truncated)

    def _inspect_battery(self, _args: dict[str, Any]) -> ToolResult:
        batteries = []
        root = Path("/sys/class/power_supply")
        for path in root.glob("BAT*") if root.exists() else ():
            row = {"name": path.name}
            for field in ("status", "capacity", "health", "cycle_count"):
                try:
                    row[field] = (path / field).read_text().strip()
                except OSError:
                    continue
            batteries.append(row)
        profile = ""
        try:
            profile = Path("/sys/firmware/acpi/platform_profile").read_text().strip()
        except OSError:
            pass
        return ToolResult("inspect_battery", True, {"batteries": batteries, "platform_profile": profile}, timestamp=_now())

    def _inspect_processes(self, args: dict[str, Any]) -> ToolResult:
        port = args.get("port")
        rows = sysinfo.processes_on_port(int(port)) if port else sysinfo.top_processes(limit=12)
        return ToolResult("inspect_processes", True, {
            "port": port, "processes": [vars(row) for row in rows],
        }, timestamp=_now())

    @staticmethod
    def _allowed_read_path(raw: str) -> Path:
        unresolved = Path(raw).expanduser()
        if unresolved.is_symlink():
            raise ValueError("symlinked files are not available to the agent")
        path = unresolved.resolve()
        cwd = Path.cwd().resolve()
        allowed_roots = [Path("/etc"), Path("/boot")]
        if (cwd / ".git").exists() or (cwd / "pyproject.toml").is_file():
            allowed_roots.append(cwd)
        if (str(path) in _DENIED_FILES or _DENIED_PATH_PARTS.intersection(path.parts)
                or path.name in (".env", ".env.local")
                or path.name.endswith((".key", ".pem", "_key"))):
            raise ValueError("sensitive file is not available to the agent")
        if not any(path == root or root in path.parents for root in allowed_roots):
            raise ValueError("path is outside the allowed inspection roots")
        if not path.is_file() or path.is_symlink():
            raise ValueError("path must be an existing regular non-symlink file")
        return path

    def _read_config_file(self, args: dict[str, Any]) -> ToolResult:
        path = self._allowed_read_path(str(args.get("path", "")))
        raw = path.read_bytes()
        truncated = len(raw) > _MAX_OUTPUT
        text = raw[:_MAX_OUTPUT].decode("utf-8", errors="replace")
        return ToolResult("read_config_file", True, {"path": str(path), "content": text},
                          timestamp=_now(), truncated=truncated)

    def _propose_action(self, args: dict[str, Any]) -> ActionProposal | ToolResult:
        argv = tuple(str(item) for item in args.get("argv", []))
        allowed, reason = validate_action_argv(argv)
        if not allowed:
            return ToolResult("propose_action", False, timestamp=_now(), error=reason)
        verify = str(args.get("verification_tool", ""))
        if self.risk_for(verify) is not ToolRisk.READ_ONLY:
            return ToolResult("propose_action", False, timestamp=_now(), error="verification must use a registered read-only tool")
        return ActionProposal(
            id=uuid.uuid4().hex[:12], purpose=str(args.get("purpose", ""))[:300],
            argv=argv, preview=shlex.join(argv), expected_result=str(args.get("expected_result", ""))[:300],
            verification_tool=verify, verification_args=dict(args.get("verification_args") or {}),
        )

    def _propose_config_edit(self, args: dict[str, Any]) -> ActionProposal | ToolResult:
        try:
            path = self._allowed_read_path(str(args.get("path", "")))
        except ValueError as exc:
            return ToolResult("propose_config_edit", False, timestamp=_now(), error=str(exc))
        if Path("/etc") not in path.parents:
            return ToolResult("propose_config_edit", False, timestamp=_now(), error="agent edits are limited to existing /etc files")
        key = str(args.get("key", ""))
        value = str(args.get("value", ""))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", key) or "\n" in value:
            return ToolResult("propose_config_edit", False, timestamp=_now(), error="invalid key or value")
        before = path.read_text(encoding="utf-8", errors="strict")
        pattern = re.compile(rf"^(\s*#?\s*){re.escape(key)}\s*=.*$", re.MULTILINE)
        replacement = f'{key}={json.dumps(value)}'
        after, count = pattern.subn(replacement, before, count=1)
        if count == 0:
            after = before.rstrip("\n") + "\n" + replacement + "\n"
        if after == before:
            return ToolResult(
                "propose_config_edit", False, timestamp=_now(),
                facts={"already_configured": True, "path": str(path), "key": key},
                error="the requested setting is already present; no change is needed",
            )
        preview = "\n".join(difflib.unified_diff(
            before.splitlines(), after.splitlines(), fromfile=str(path), tofile=str(path), lineterm="",
        ))
        verify = str(args.get("verification_tool", ""))
        if self.risk_for(verify) is not ToolRisk.READ_ONLY:
            return ToolResult("propose_config_edit", False, timestamp=_now(), error="verification must use a registered read-only tool")
        return ActionProposal(
            id=uuid.uuid4().hex[:12], purpose=str(args.get("purpose", ""))[:300],
            operation="config_edit", preview=preview, expected_result=str(args.get("expected_result", ""))[:300],
            verification_tool=verify, verification_args=dict(args.get("verification_args") or {}),
            path=str(path), key=key, value=value,
        )

    def apply_config_edit(self, proposal: ActionProposal, *, dry_run: bool = False) -> ToolResult:
        """Apply exactly the already-previewed edit, using sudo only for the copy."""
        regenerated = self._propose_config_edit({
            "purpose": proposal.purpose, "path": proposal.path, "key": proposal.key,
            "value": proposal.value, "expected_result": proposal.expected_result,
            "verification_tool": proposal.verification_tool,
            "verification_args": proposal.verification_args,
        })
        if not isinstance(regenerated, ActionProposal) or regenerated.preview != proposal.preview:
            return ToolResult("propose_config_edit", False, timestamp=_now(), error="file changed since approval; review a new diff")
        if dry_run:
            return ToolResult("propose_config_edit", True, {"dry_run": True, "path": proposal.path}, timestamp=_now())
        path = Path(proposal.path)
        before = path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^(\s*#?\s*){re.escape(proposal.key)}\s*=.*$", re.MULTILINE)
        replacement = f'{proposal.key}={json.dumps(proposal.value)}'
        after, count = pattern.subn(replacement, before, count=1)
        if count == 0:
            after = before.rstrip("\n") + "\n" + replacement + "\n"
        fd, temporary = tempfile.mkstemp(prefix="novato-edit-", dir=str(Path.home()))
        suffix = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.novato.bak.{suffix}")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(after)
            os.chmod(temporary, path.stat().st_mode & 0o777)
            prefix = ["sudo"] if not os.access(path, os.W_OK) else []
            backup_argv = [*prefix, "cp", "--preserve=mode,ownership,timestamps",
                           str(path), str(backup)]
            install_argv = [*prefix, "cp", "--preserve=mode,ownership", temporary, str(path)]
            logger.log_event(logger.EVENT_EXEC, shlex.join(backup_argv),
                             note=f"agent config backup {proposal.id}")
            rc = subprocess.run(backup_argv).returncode
            if rc == 0:
                logger.log_event(logger.EVENT_EXEC, shlex.join(install_argv),
                                 note=f"agent config edit {proposal.id}")
                rc = subprocess.run(install_argv).returncode
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        ok = rc == 0 and replacement in path.read_text(encoding="utf-8", errors="replace")
        return ToolResult("propose_config_edit", ok, {"path": str(path), "backup": str(backup)},
                          exit_status=rc, timestamp=_now(), error="" if ok else "edit or verification failed")
