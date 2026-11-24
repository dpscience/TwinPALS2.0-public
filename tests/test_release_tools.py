# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Release ownership, rollback, evidence binding and shutdown gates; no app servers."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import finalize_release as finalizer
import package_release as packaging
import verify_portable as portable


@pytest.mark.parametrize('kind',['catalogue'])
def test_factory_database_zip_never_contains_user_edits(tmp_path,monkeypatch,kind):
    import zipfile
    from backend.material_database import MaterialDatabase
    project=Path(__file__).resolve().parents[1]
    monkeypatch.setattr(packaging,'ROOT',tmp_path)
    (tmp_path/'tmp').mkdir()
    output=tmp_path/'release'
    seed_file='seed/factory_catalogue.json'
    relative=f'data/{kind}.tpdb'
    seed=(project/seed_file).read_bytes()
    manifest=release(output,{seed_file:seed,'app.exe':b'fixture'},'2.1.0')
    expected=packaging.factory_database(output,output/relative)
    manifest['initial_data']={relative:expected}
    packaging.write_json(output/packaging.MANIFEST,manifest)
    db=MaterialDatabase(output/relative,output/seed_file)
    entry=db.entries()[0]
    entry['name']='PRIVATE USER MATERIAL';db.put(entry,entry['revision'])
    user_hash=packaging.sha256(db.path)
    archive=tmp_path/'release.zip';packaging.make_zip(output,archive,'2.1.0')
    assert packaging.sha256(db.path)==user_hash
    with zipfile.ZipFile(archive) as z:
        value=z.read('release/'+relative)
        assert b'PRIVATE USER MATERIAL' not in value
        assert len(value)==expected['bytes']
    staged=tmp_path/'staged';staged.mkdir()
    (staged/'data').mkdir();(staged/relative).write_bytes(value)
    packaging.install_initial_data(staged,output,manifest)
    assert packaging.sha256(db.path)==user_hash
    empty=tmp_path/'new-install';empty.mkdir()
    packaging.install_initial_data(staged,empty,manifest)
    assert (empty/relative).read_bytes()==value


def release(folder, content, version):
    folder.mkdir(parents=True)
    for name, value in content.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    manifest = {"format": "twinpals-portable-release", "format_version": 1, "version": version,
                "files": {name: {"bytes": len(value), "sha256": packaging.sha256(folder/name)}
                          for name, value in content.items()}, "validation": {}}
    packaging.write_json(folder / packaging.MANIFEST, manifest)
    return manifest


def test_installer_includes_only_manifest_program_files(tmp_path, monkeypatch):
    import build_installer

    folder = tmp_path / 'Used portable'
    release(folder, {'TwinPALS.exe': b'payload'}, '2.0.0')
    (folder / 'data').mkdir()
    (folder / 'data' / 'catalogue.tpdb').write_bytes(b'private material')
    (folder / 'personal-notes.txt').write_text('user-owned file')
    output = tmp_path / 'dist' / 'Setup.exe'

    def compile_fixture(command, check):
        include = Path(next(arg.removeprefix('/DPayloadList=') for arg in command if arg.startswith('/DPayloadList=')))
        directives = include.read_text(encoding='utf-8-sig').splitlines()
        assert len(directives) == 2
        assert all(any(name in line for name in ('TwinPALS.exe', packaging.MANIFEST)) for line in directives)
        (include.parent / 'TwinPALS-setup.exe').write_bytes(b'finished installer')

    monkeypatch.setattr(build_installer.subprocess, 'run', compile_fixture)
    assert build_installer.build_installer(folder, output, 'test-compiler') == packaging.sha256(output)
    assert output.with_suffix('.exe.sha256').read_text().split() == [packaging.sha256(output), output.name]
    with pytest.raises(ValueError, match='preserve existing artifacts'):
        build_installer.build_installer(folder, output, 'test-compiler')


def test_installed_and_portable_default_data_locations(tmp_path, monkeypatch):
    from backend.app import default_data_directory
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'account'))
    assert default_data_directory(tmp_path) == tmp_path / 'data'
    (tmp_path / 'twinpals-installed.ini').write_text('[TwinPALS]\nLayout=installed-v1\n')
    assert default_data_directory(tmp_path) == tmp_path / 'account' / 'TwinPALS' / 'Data'
    monkeypatch.setattr(sys, 'frozen', False)
    assert default_data_directory(tmp_path) == tmp_path / 'data'


def test_owned_update_skips_identical_copies_preserving_users(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    output, staged = tmp_path/"release", tmp_path/"staged"
    release(output, {"same.bin": b"same", "change.bin": b"before", "removed.bin": b"old"}, "0.1.0")
    release(staged, {"same.bin": b"same", "change.bin": b"after", "new.bin": b"new"}, "0.1.1")
    (output/"data").mkdir()
    (output/"data/user.db").write_bytes(b"keep user data")
    copied = []
    original = packaging.shutil.copy2
    def tracked(source, target, *args, **kwargs):
        copied.append((Path(source), Path(target)))
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(packaging.shutil, "copy2", tracked)
    backup = packaging.install_owned(staged, output, True)
    assert not any(source.name == "same.bin" for source, _ in copied)
    assert not (backup/"same.bin").exists()
    assert (backup/"change.bin").read_bytes() == b"before"
    assert (backup/"removed.bin").read_bytes() == b"old"
    assert (output/"data/user.db").read_bytes() == b"keep user data"
    assert packaging.verify_folder(output)["version"] == "0.1.1"


def test_failed_update_restores_changed_removed_and_damaged_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    output, staged = tmp_path/"release", tmp_path/"staged"
    previous = release(output, {"a.bin": b"before", "same.bin": b"same", "removed.bin": b"old"}, "0.1.0")
    release(staged, {"a.bin": b"after", "same.bin": b"same", "z-new.bin": b"new"}, "0.1.1")
    original = packaging.shutil.copy2
    failed = False
    def fault(source, target, *args, **kwargs):
        nonlocal failed
        if Path(source) == staged/"z-new.bin" and not failed:
            failed = True
            (output/"same.bin").write_bytes(b"unexpected concurrent damage")
            raise OSError("injected installation failure")
        return original(source, target, *args, **kwargs)
    monkeypatch.setattr(packaging.shutil, "copy2", fault)
    with pytest.raises(OSError, match="injected"):
        packaging.install_owned(staged, output, True)
    assert packaging.verify_folder(output) == previous
    assert not (output/"z-new.bin").exists()


def test_update_refuses_unowned_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    output, staged = tmp_path/"release", tmp_path/"staged"
    release(output, {"a.bin": b"old"}, "0.1.0")
    (output/"user-note.txt").write_bytes(b"unowned")
    release(staged, {"a.bin": b"new", "user-note.txt": b"overwrite"}, "0.1.1")
    with pytest.raises(ValueError, match="Unowned"):
        packaging.install_owned(staged, output, True)
    assert (output/"user-note.txt").read_bytes() == b"unowned"
    assert (output/"a.bin").read_bytes() == b"old"


def test_update_refuses_modified_owned_file(tmp_path, monkeypatch):
    monkeypatch.setattr(packaging, "ROOT", tmp_path)
    output, staged = tmp_path/"release", tmp_path/"staged"
    release(output, {"a.bin": b"old"}, "0.1.0")
    release(staged, {"a.bin": b"new"}, "0.1.1")
    (output/"a.bin").write_bytes(b"changed externally")
    with pytest.raises(ValueError, match="differs"):
        packaging.install_owned(staged, output, True)
    assert (output/"a.bin").read_bytes() == b"changed externally"


@pytest.fixture
def evidence_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(finalizer, "ROOT", tmp_path)
    test_log = tmp_path/"test.log"
    test_log.write_text("fixture result: 7 passed", encoding="utf-8")
    ui = {"ok": True, "version": "0.1.1", "server_stopped": True, "pageErrors": [], "httpErrors": [],
          "frontend_files": {"index.html": "reviewed-frontend-hash"}}
    ui_path = tmp_path/"ui.json"
    ui_path.write_text(json.dumps(ui), encoding="utf-8")
    evidence = {"format": "twinpals-release-evidence", "format_version": 1, "application_version": "0.1.1",
                "ui_report_sha256": packaging.sha256(ui_path),
                "checks": [{"name": "fixture check", "command": "fixture test", "status": "passed",
                            "report": "test.log", "report_sha256": packaging.sha256(test_log), "counts": {"passed": 7}}]}
    manifest = {"version": "0.1.1", "files": {"frontend/dist/index.html": {"sha256": "reviewed-frontend-hash", "bytes": 1}}}
    return evidence, ui, ui_path, manifest


def test_finalizer_uses_explicit_counts(evidence_fixture):
    evidence, ui, ui_path, manifest = evidence_fixture
    assert finalizer.validate_evidence(evidence, ui, ui_path, manifest)[0]["counts"] == {"passed": 7}


@pytest.mark.parametrize("change", ["version", "frontend", "report_hash", "test_failed", "ui_running"])
def test_finalizer_rejects_stale_or_failed_evidence(evidence_fixture, change):
    evidence, ui, ui_path, manifest = copy.deepcopy(evidence_fixture)
    if change == "version": evidence["application_version"] = "0.1.0"
    if change == "frontend": manifest["files"]["frontend/dist/index.html"]["sha256"] = "new-build-hash"
    if change == "report_hash": evidence["checks"][0]["report_sha256"] = "stale"
    if change == "test_failed": evidence["checks"][0]["status"] = "failed"
    if change == "ui_running": ui["server_stopped"] = False
    with pytest.raises(ValueError):
        finalizer.validate_evidence(evidence, ui, ui_path, manifest)


def test_shutdown_gate_detects_live_port_and_accepts_closed_port():
    # A scoped listening socket proves the port check; no server process is started.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        evidence = {"server_shutdown": {"status": "passed", "owned_processes_stopped": True,
                    "ports": [port], "checked_at": "2026-10-17T00:00:00Z"}}
        with pytest.raises(ValueError, match="still listening"):
            finalizer.check_shutdown(evidence)
        with pytest.raises(RuntimeError, match="remains open"):
            portable.require_closed_port(port, timeout=0)
    assert finalizer.check_shutdown(evidence)["ports_rechecked_closed_at"]
    portable.require_closed_port(port, timeout=0)
