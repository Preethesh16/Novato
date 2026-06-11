"""End-to-end flow tests for the App orchestrator (no real installs)."""

from __future__ import annotations

import pytest

from novato import config as cfgmod
from novato import executor as execmod
from novato import searcher as searchmod
from novato.detector import SystemInfo
from novato.intent import IntentResolver
from novato.main import App
from novato.presenter import Presenter
from novato.searcher import SearchResult


@pytest.fixture()
def arch_system():
    return SystemInfo(
        distro_id="arch", distro_name="Arch Linux", distro_version="",
        package_manager="pacman", install_cmd="sudo pacman -S",
        search_cmd="pacman -Ss", supports_aur=True, aur_helper="yay",
        shell="zsh", supported=True,
    )


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def _scripted_app(arch_system, answers, monkeypatch, dry_run=False, config=None):
    """Build an App whose presenter input is a scripted list of answers."""
    it = iter(answers)
    presenter = Presenter(input_fn=lambda prompt: next(it, "q"))
    app = App(
        system=arch_system,
        config=config or cfgmod.Config(mode="basic"),
        presenter=presenter,
        resolver=IntentResolver(),
        dry_run=dry_run,
    )
    return app


def test_query_flow_dry_run_installs_nothing(arch_system, isolated_home, monkeypatch):
    # Stub repo search so the test is offline and deterministic.
    monkeypatch.setattr(searchmod, "search_candidates",
                        lambda c, pm, **k: [SearchResult(name=n, source="pacman",
                                                         repo="extra") for n in c])
    # Spy on execute to ensure nothing actually runs.
    called = {"executed": False}
    monkeypatch.setattr(execmod, "_stream",
                        lambda *a, **k: called.__setitem__("executed", True) or 0)

    app = _scripted_app(arch_system, ["1", "y"], monkeypatch, dry_run=True)
    rc = app.run_query("i want to edit videos")
    assert rc == 0
    assert called["executed"] is False  # dry-run never streams


def test_literal_package_name_falls_back_to_direct_search(
    arch_system, isolated_home, monkeypatch
):
    # "install firefox" isn't a curated intent, and the default resolver can't
    # map it. Novato must still find it via a direct repo search on "firefox".
    seen = {}
    monkeypatch.setattr(
        "novato.main.search_candidates",
        lambda c, pm, **k: seen.update(candidates=c) or [
            SearchResult(name=n, source="pacman", repo="extra") for n in c
        ],
    )
    app = _scripted_app(arch_system, ["1", "y"], monkeypatch, dry_run=True)
    rc = app.run_query("install firefox")
    assert rc == 0
    # "install" is a stopword; only the real package name is searched.
    assert seen["candidates"] == ["firefox"]


def test_already_installed_offers_update_via_same_source(
    arch_system, isolated_home, monkeypatch
):
    # An AUR-installed package must be updated through the AUR helper, not pacman.
    import novato.main as mainmod
    from novato import installed as instmod
    from novato.executor import ExecResult

    monkeypatch.setattr(
        instmod, "get_info",
        lambda pkg, pm: instmod.InstalledInfo(pkg, "1.85.115-1", instmod.ORIGIN_AUR),
    )
    captured = {}
    monkeypatch.setattr(
        mainmod, "execute",
        lambda cmd, **k: captured.update(cmd=cmd) or ExecResult(cmd, 0, executed=True),
    )
    # answers: "y" = yes, update it; "y" = confirm the command.
    app = _scripted_app(arch_system, ["y", "y"], monkeypatch)
    rc = app._install("brave-bin", source="aur")
    assert rc == 0
    assert captured["cmd"] == "yay -S brave-bin"


def test_already_installed_decline_runs_nothing(
    arch_system, isolated_home, monkeypatch
):
    import novato.main as mainmod
    from novato import installed as instmod

    monkeypatch.setattr(
        instmod, "get_info",
        lambda pkg, pm: instmod.InstalledInfo(pkg, "151.0.4-1", instmod.ORIGIN_OFFICIAL),
    )
    called = {"executed": False}
    monkeypatch.setattr(
        mainmod, "execute",
        lambda cmd, **k: called.__setitem__("executed", True),
    )
    app = _scripted_app(arch_system, ["n"], monkeypatch)
    rc = app._install("firefox")
    assert rc == 0
    assert called["executed"] is False


def test_query_flow_quit(arch_system, isolated_home, monkeypatch):
    monkeypatch.setattr("novato.main.search_candidates",
                        lambda c, pm, **k: [SearchResult(name=n, source="pacman")
                                            for n in c])
    app = _scripted_app(arch_system, ["q"], monkeypatch)
    rc = app.run_query("edit videos")
    assert rc == 0


def test_unsupported_distro_refuses(isolated_home, monkeypatch):
    unsupported = SystemInfo(
        distro_id="plan9", distro_name="Plan 9", distro_version="",
        package_manager="unknown", install_cmd="", search_cmd="",
        supports_aur=False, aur_helper=None, shell="rc", supported=False,
    )
    app = App(system=unsupported, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: "q"))
    assert app.run_query("edit videos") == 2


def test_analyze_error_typo(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(mistake=True),
              presenter=Presenter(input_fn=lambda p: "n"))  # decline the fix
    rc = app.analyze_error("sudo pacmna -S vlc", 127,
                           "bash: pacmna: command not found")
    assert rc == 0


def test_confirm_is_eof_safe():
    # Regression: a presenter with no input (EOF) must not crash; safest is "no".
    def raise_eof(prompt):
        raise EOFError
    p = Presenter(input_fn=raise_eof)
    assert p.confirm("sudo pacman -S vlc") is False
    assert p.prompt_choice(3) is None


def test_slash_status(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: ""))
    assert app.slash(["/status"]) == 0


def test_slash_switch_persists(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: ""))
    app.slash(["/switch", "basic"])
    assert cfgmod.load_config().mode == "basic"


def test_slash_explain_toggle(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: ""))
    app.slash(["/explain", "on"])
    assert cfgmod.load_config().explain is True
