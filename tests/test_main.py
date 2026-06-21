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


def test_analyze_error_stays_silent_on_ctrl_c(arch_system, isolated_home, monkeypatch):
    # Exit 130 = the user's own Ctrl+C — not a mistake. The analyzer must
    # return silently without even consulting the backends.
    app = App(system=arch_system, config=cfgmod.Config(mistake=True),
              presenter=Presenter(input_fn=lambda p: "n"))
    spoke = {"called": False}
    monkeypatch.setattr(app.ui, "show_correction",
                        lambda c: spoke.__setitem__("called", True))
    for code in (130, 143, 137):
        assert app.analyze_error("sleep 100", code, "") == 0
    assert spoke["called"] is False


def test_execute_handles_ctrl_c_cleanly(monkeypatch, isolated_home):
    # Ctrl+C during a streamed install must not raise — it returns exit 130.
    from novato import executor as execmod2

    def boom(cmd, sink):
        raise KeyboardInterrupt
    monkeypatch.setattr(execmod2, "_stream", boom)
    result = execmod2.execute("sudo pacman -S vlc")
    assert result.exit_code == 130
    assert result.executed is True
    assert "cancelled" in result.reason


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


# -- New beginner-facing commands ------------------------------------------

def test_howto_task_short_circuits_package_search(arch_system, isolated_home, monkeypatch):
    # "unzip messi file" is a terminal task, not a package request: it must be
    # answered directly and must NOT trigger a repository search.
    searched = {"called": False}
    monkeypatch.setattr("novato.main.search_candidates",
                        lambda *a, **k: searched.__setitem__("called", True) or [])
    app = _scripted_app(arch_system, ["n"], monkeypatch, dry_run=True)
    rc = app.run_query("unzip messi file")
    assert rc == 0
    assert searched["called"] is False


def test_package_query_still_reaches_search(arch_system, isolated_home, monkeypatch):
    # A genuine package intent must fall through to the package flow.
    seen = {"called": False}
    monkeypatch.setattr(
        "novato.main.search_candidates",
        lambda c, pm, **k: seen.__setitem__("called", True) or [
            SearchResult(name=n, source="pacman", repo="extra") for n in c
        ],
    )
    app = _scripted_app(arch_system, ["q"], monkeypatch, dry_run=True)
    app.run_query("i want to edit videos")
    assert seen["called"] is True


def test_disk_full_query_routes_to_disk(arch_system, isolated_home, monkeypatch):
    from novato import sysinfo as sysmod
    routed = {"disk": False}
    monkeypatch.setattr(sysmod, "disk_mounts",
                        lambda **k: routed.__setitem__("disk", True) or [])
    monkeypatch.setattr(sysmod, "largest_dirs", lambda *a, **k: [])
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: "q"))
    app.run_query("why is my disk full")
    assert routed["disk"] is True


def test_slash_cheat_known_and_unknown(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: ""))
    assert app.slash(["/cheat", "files"]) == 0
    assert app.slash(["/cheat"]) == 0
    assert app.slash(["/cheat", "nonsense"]) == 1


def test_slash_man_known_and_unknown(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: ""))
    assert app.slash(["/man", "unzip", "a", "file"]) == 0
    assert app.slash(["/man", "frobnicate", "the", "widget"]) == 1


def test_slash_explain_command_does_not_toggle(arch_system, isolated_home):
    # /explain with a real command explains it rather than toggling the setting.
    app = App(system=arch_system, config=cfgmod.Config(explain=False),
              presenter=Presenter(input_fn=lambda p: ""))
    assert app.slash(["/explain", "ls", "-la"]) == 0
    assert cfgmod.load_config().explain is False  # toggle untouched


def test_slash_process_lists_and_can_decline(arch_system, isolated_home, monkeypatch):
    from novato import sysinfo as sysmod
    monkeypatch.setattr(sysmod, "top_processes",
                        lambda **k: [sysmod.ProcInfo(pid=42, name="firefox")])
    # 'q' at the kill prompt -> nothing is killed.
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: "q"))
    assert app.slash(["/process"]) == 0


def test_update_system_command_is_distro_specific(arch_system, isolated_home):
    app = App(system=arch_system, config=cfgmod.Config(),
              presenter=Presenter(input_fn=lambda p: "n"))
    assert app._system_update_command() == "sudo pacman -Syu"


def test_switch_to_online_without_key_warns(arch_system, isolated_home, monkeypatch, capsys):
    cfgmod.save_config(cfgmod.Config(mode="basic"))
    app = _scripted_app(arch_system, [], monkeypatch)
    app.slash(["/switch", "online"])
    out = capsys.readouterr().out
    assert "Switched to online mode" in out
    assert "Groq API key" in out  # readiness warning


def test_switch_to_online_with_key_is_silent(arch_system, isolated_home, monkeypatch, capsys):
    cfgmod.save_config(cfgmod.Config(mode="basic", groq_api_key="gsk_x"))
    app = _scripted_app(arch_system, [], monkeypatch)
    app.slash(["/switch", "online"])
    out = capsys.readouterr().out
    assert "Switched to online mode" in out
    assert "Groq API key" not in out  # ready -> no warning


def test_switch_to_offline_without_model_warns(arch_system, isolated_home, monkeypatch, capsys):
    cfgmod.save_config(cfgmod.Config(mode="basic"))
    app = _scripted_app(arch_system, [], monkeypatch)
    app.slash(["/switch", "offline"])
    out = capsys.readouterr().out
    assert "download-model" in out


# -- Smart "update except <packages>" -----------------------------------------

def _app_with_packages(arch_system, monkeypatch, packages):
    """An App whose 'installed packages' are a fixed set (for exclusion tests)."""
    import novato.installed as installedmod
    monkeypatch.setattr(installedmod, "installed_versions",
                        lambda pm: {p: "1.0" for p in packages})
    return _scripted_app(arch_system, [], monkeypatch)


def test_update_with_exclusion_ignores_matched_package(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch,
                            ["android-studio", "visual-studio-code-bin", "firefox"])
    app.run_query("update my arch system without updating android studio")
    out = capsys.readouterr().out
    assert "sudo pacman -Syu --ignore=android-studio" in out
    assert "Skipping: android-studio" in out


def test_exclusion_phrase_does_not_overmatch(arch_system, isolated_home, monkeypatch, capsys):
    """'android studio' must not also drag in 'visual-studio-code' via 'studio'."""
    app = _app_with_packages(arch_system, monkeypatch,
                            ["android-studio", "visual-studio-code-bin"])
    app.run_query("update everything except android studio")
    out = capsys.readouterr().out
    assert "android-studio" in out
    assert "visual-studio-code-bin" not in out


def test_update_without_exclusion_is_plain(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch, ["firefox"])
    app.run_query("update my system")
    out = capsys.readouterr().out
    assert "sudo pacman -Syu" in out
    assert "--ignore" not in out
    # No misleading "replace the example name(s)" footer on a system update.
    assert "Replace the example" not in out


def test_exclusion_with_no_installed_match_explains(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch, ["firefox"])
    app.run_query("update everything except photoshop")
    out = capsys.readouterr().out
    assert "sudo pacman -Syu" in out
    assert "--ignore" not in out
    assert "won't touch it anyway" in out


def test_update_exclusions_resolves_phrases(arch_system, isolated_home, monkeypatch):
    app = _app_with_packages(
        arch_system, monkeypatch,
        ["android-studio", "visual-studio-code-bin", "qemu-emulators-full", "firefox"],
    )
    # Two products, comma/or separated, each matched as a whole phrase.
    ignore = app._update_exclusions("update but not android studio or visual studio code")
    assert ignore == ["android-studio", "visual-studio-code-bin"]


# -- Package removal: "uninstall firefox" -------------------------------------

def test_remove_offers_uninstall_not_install(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch, ["firefox", "vlc"])
    monkeypatch.setattr(execmod, "_stream", lambda *a, **k: 0)
    app.dry_run = True
    app.run_query("remove firefox")
    out = capsys.readouterr().out
    assert "sudo pacman -Rs firefox" in out
    assert "pacman -S firefox" not in out  # must NOT offer to install


def test_remove_not_installed_says_so(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch, ["firefox"])
    app.dry_run = True
    app.run_query("uninstall photoshop")
    out = capsys.readouterr().out
    assert "nothing to remove" in out
    assert "-Rs" not in out


def test_remove_phrase_matches_real_package(arch_system, isolated_home, monkeypatch, capsys):
    app = _app_with_packages(arch_system, monkeypatch,
                            ["visual-studio-code-bin", "firefox"])
    app.dry_run = True
    app.run_query("uninstall visual studio code")
    out = capsys.readouterr().out
    assert "sudo pacman -Rs visual-studio-code-bin" in out


def test_remove_a_file_is_still_file_deletion(arch_system, isolated_home, monkeypatch, capsys):
    """'remove a file' is a how-to (rm), not package removal."""
    app = _app_with_packages(arch_system, monkeypatch, ["firefox"])
    app.dry_run = True
    app.run_query("remove a file")
    out = capsys.readouterr().out
    assert "rm" in out
    assert "-Rs" not in out


def test_remove_command_per_distro():
    cases = {"pacman": "sudo pacman -Rs vlc", "apt": "sudo apt remove vlc",
             "dnf": "sudo dnf remove vlc", "zypper": "sudo zypper remove vlc"}
    for pm, expected in cases.items():
        sysinfo = SystemInfo(
            distro_id="x", distro_name="X", distro_version="", package_manager=pm,
            install_cmd="", search_cmd="", supports_aur=False, aur_helper=None,
            shell="bash", supported=True)
        app = App(system=sysinfo, config=cfgmod.Config(),
                  presenter=Presenter(), resolver=IntentResolver())
        assert app._remove_command("vlc") == expected


# -- Guarded file deletion ----------------------------------------------------

def test_delete_named_file_is_offered(arch_system, isolated_home, monkeypatch, capsys):
    app = _scripted_app(arch_system, [], monkeypatch, dry_run=True)
    app.run_query("delete report.txt")
    out = capsys.readouterr().out
    assert "rm report.txt" in out
    assert "permanently deletes" in out


def test_delete_routes_files_not_packages(arch_system, isolated_home, monkeypatch, capsys):
    # A dotted target is a file to delete, not a package to uninstall.
    app = _app_with_packages(arch_system, monkeypatch, ["firefox"])
    app.dry_run = True
    app.run_query("delete report.txt")
    out = capsys.readouterr().out
    assert "rm report.txt" in out
    assert "nothing to remove" not in out


def test_delete_system_path_is_shown_not_run(arch_system, isolated_home, monkeypatch, capsys):
    app = _scripted_app(arch_system, ["y"], monkeypatch)  # would say yes...
    monkeypatch.setattr(execmod, "_stream", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not execute a blocked rm")))
    app.run_query("delete /etc/passwd")
    out = capsys.readouterr().out
    assert "rm /etc/passwd" in out          # shown for reference
    # safety blocks it, so it was never offered for execution (no AssertionError)
