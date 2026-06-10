"""Tests for system detection (distro, package manager, shell)."""

from __future__ import annotations

import textwrap


from novato import detector


def _write_os_release(tmp_path, content: str) -> str:
    path = tmp_path / "os-release"
    path.write_text(textwrap.dedent(content))
    return str(path)


def test_parse_quoted_values(tmp_path):
    path = _write_os_release(tmp_path, '''
        ID=arch
        NAME="Arch Linux"
        PRETTY_NAME="Arch Linux"
    ''')
    data = detector._read_os_release(path)
    assert data["ID"] == "arch"
    assert data["NAME"] == "Arch Linux"


def test_missing_os_release_returns_empty():
    assert detector._read_os_release("/nonexistent/os-release") == {}


def test_detect_arch(tmp_path):
    path = _write_os_release(tmp_path, '''
        ID=arch
        PRETTY_NAME="Arch Linux"
    ''')
    info = detector.detect_system(path)
    assert info.distro_id == "arch"
    assert info.package_manager == "pacman"
    assert info.install_cmd == "sudo pacman -S"
    assert info.supports_aur is True
    assert info.supported is True


def test_detect_ubuntu(tmp_path):
    path = _write_os_release(tmp_path, '''
        ID=ubuntu
        VERSION_ID="24.04"
        PRETTY_NAME="Ubuntu 24.04 LTS"
    ''')
    info = detector.detect_system(path)
    assert info.package_manager == "apt"
    assert info.install_cmd == "sudo apt install"
    assert info.supports_aur is False
    assert info.distro_version == "24.04"


def test_detect_fedora(tmp_path):
    path = _write_os_release(tmp_path, 'ID=fedora\nPRETTY_NAME="Fedora 40"\n')
    info = detector.detect_system(path)
    assert info.package_manager == "dnf"


def test_unknown_distro_falls_back_via_id_like(tmp_path):
    # A hypothetical Ubuntu remix not in the map but ID_LIKE=ubuntu.
    path = _write_os_release(tmp_path, '''
        ID=mythbuntu
        ID_LIKE="ubuntu debian"
        PRETTY_NAME="Mythbuntu"
    ''')
    info = detector.detect_system(path)
    assert info.package_manager == "apt"
    assert info.supported is True


def test_fully_unknown_distro_marked_unsupported(tmp_path):
    path = _write_os_release(tmp_path, 'ID=plan9\nPRETTY_NAME="Plan 9"\n')
    info = detector.detect_system(path)
    assert info.supported is False
    assert info.package_manager == "unknown"


def test_detect_shell_from_env():
    assert detector.detect_shell({"SHELL": "/usr/bin/zsh"}) == "zsh"
    assert detector.detect_shell({"SHELL": "/bin/bash"}) == "bash"
    assert detector.detect_shell({}) == "unknown"


def test_system_info_as_dict_is_serialisable(tmp_path):
    import json
    path = _write_os_release(tmp_path, "ID=arch\n")
    info = detector.detect_system(path)
    # Should round-trip through JSON without error.
    assert json.loads(json.dumps(info.as_dict()))["package_manager"] == "pacman"
