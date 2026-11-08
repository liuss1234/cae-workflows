from pathlib import Path

import pytest

from tools.install_skills import available_skills, install, read_skill_name, resolve_root


REPOSITORY = Path(__file__).resolve().parents[1]


def test_every_skill_name_matches_its_directory():
    names = available_skills()
    assert names
    for name in names:
        assert read_skill_name(REPOSITORY / "skills" / name) == name


def test_install_copies_relative_structure(tmp_path):
    installed = install(["cfd-preprocessing"], tmp_path)
    assert installed == ["cfd-preprocessing"]
    target = tmp_path / "cfd-preprocessing"
    assert (target / "SKILL.md").is_file()
    assert (target / "agents" / "openai.yaml").is_file()


def test_install_skips_existing_without_force(tmp_path):
    destination = tmp_path / "cfd-preprocessing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    assert install(["cfd-preprocessing"], tmp_path) == []
    assert marker.read_text(encoding="utf-8") == "keep"


def test_install_force_replaces_existing(tmp_path):
    destination = tmp_path / "cfd-preprocessing"
    destination.mkdir()
    (destination / "stale.txt").write_text("stale", encoding="utf-8")
    assert install(["cfd-preprocessing"], tmp_path, force=True) == ["cfd-preprocessing"]
    assert (destination / "SKILL.md").is_file()
    assert not (destination / "stale.txt").exists()


def test_dry_run_writes_nothing(tmp_path):
    assert install(["cfd-preprocessing"], tmp_path, dry_run=True) == ["cfd-preprocessing"]
    assert not (tmp_path / "cfd-preprocessing").exists()


def test_unknown_skill_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        install(["no-such-skill"], tmp_path)


def test_environment_variable_sets_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh-home"))
    assert resolve_root("dsh") == tmp_path / "dsh-home" / "skills"


def test_default_root_falls_back_to_user_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert resolve_root("codex") == tmp_path / ".codex" / "skills"
