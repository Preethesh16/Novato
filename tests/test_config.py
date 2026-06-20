# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for config persistence: round-trips must be stable and lossless."""

import pytest

from novato import config as cfgmod


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVATO_HOME", str(tmp_path / ".novato"))
    yield tmp_path


def test_save_load_round_trip_is_stable(isolated_home):
    """Saving then loading must reproduce the same config, byte-for-byte on disk."""
    cfg = cfgmod.Config(mode="online", explain=True, groq_api_key="key123")
    cfgmod.save_config(cfg)
    first = cfgmod.config_path().read_text()

    loaded = cfgmod.load_config()
    assert loaded.mode == "online"
    assert loaded.explain is True
    assert loaded.groq_api_key == "key123"

    # Re-saving the loaded config must produce identical bytes — no drift.
    cfgmod.save_config(loaded)
    second = cfgmod.config_path().read_text()
    assert first == second


def test_extra_does_not_nest_across_many_round_trips(isolated_home):
    """Regression: `extra` used to wrap itself one level deeper on every save."""
    cfgmod.save_config(cfgmod.Config())
    for _ in range(5):
        cfg = cfgmod.load_config()
        cfgmod.save_config(cfg)
    final = cfgmod.load_config()
    # extra must stay flat (empty here), never become {"extra": {"extra": ...}}.
    assert final.extra == {}


def test_unknown_keys_are_preserved_in_extra(isolated_home):
    """Forward-compat: keys from a newer version survive a load/save round-trip."""
    path = cfgmod.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"mode": "basic", "future_flag": 42}')

    cfg = cfgmod.load_config()
    assert cfg.extra.get("future_flag") == 42

    # And it should not get double-wrapped on the next round-trip.
    cfgmod.save_config(cfg)
    again = cfgmod.load_config()
    assert again.extra.get("future_flag") == 42
    assert "extra" not in again.extra


def test_update_config_round_trips_cleanly(isolated_home):
    cfgmod.update_config(mode="online")
    cfgmod.update_config(explain=True)
    cfg = cfgmod.load_config()
    assert cfg.mode == "online"
    assert cfg.explain is True
    assert cfg.extra == {}
