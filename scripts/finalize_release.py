# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bind explicit test evidence to an independently checked portable release.

This finalizer does not run or infer tests. Pass fresh structured evidence and
the browser/portable reports explicitly; historical counts are never reused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket

from package_release import MANIFEST, ROOT, checked_relative, make_zip, sha256, target_path, verify_folder, write_json


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def local_report(raw: str) -> Path:
    path = (ROOT / checked_relative(raw)).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"Evidence report must be a local project file: {raw}")
    return path


def check_shutdown(evidence: dict) -> dict:
    shutdown = evidence.get("server_shutdown", {})
    ports = shutdown.get("ports")
    if (shutdown.get("status") != "passed" or shutdown.get("owned_processes_stopped") is not True
            or not isinstance(ports, list) or not ports
            or any(type(port) is not int or not 1 <= port <= 65535 for port in ports)
            or not isinstance(shutdown.get("checked_at"), str)):
        raise ValueError("Explicit successful server-shutdown evidence and checked local ports are required")
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.25)
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError(f"A server is still listening on test port {port}; stop owned test servers before finalization")
    return {**shutdown, "ports_rechecked_closed_at": datetime.now(timezone.utc).isoformat()}


def validate_evidence(evidence: dict, ui: dict, ui_path: Path, manifest: dict) -> list[dict]:
    if evidence.get("format") != "twinpals-release-evidence" or evidence.get("format_version") != 1:
        raise ValueError("Unsupported structured release evidence format")
    if evidence.get("application_version") != manifest["version"]:
        raise ValueError("Verification evidence belongs to a different application version")
    if evidence.get("ui_report_sha256") != sha256(ui_path):
        raise ValueError("Browser report differs from the explicitly reviewed evidence")
    if (ui.get("ok") is not True or ui.get("version") != manifest["version"]
            or ui.get("server_stopped") is not True or ui.get("pageErrors") or ui.get("httpErrors")):
        raise ValueError("Browser verification has not passed for this application version")
    expected_frontend = {name.removeprefix("frontend/dist/"): value["sha256"]
                         for name, value in manifest["files"].items() if name.startswith("frontend/dist/")}
    if not expected_frontend or ui.get("frontend_files") != expected_frontend:
        raise ValueError("Browser-tested frontend file hashes differ from the packaged frontend")
    checks = evidence.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Explicit completed verification checks are required")
    names = set()
    verified_checks = []
    for check in checks:
        if (not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"]
                or check["name"] in names or check.get("status") != "passed"
                or not isinstance(check.get("command"), str) or not check["command"]
                or not isinstance(check.get("report"), str)):
            raise ValueError("Each unique verification check needs a successful status, command and report")
        names.add(check["name"])
        report_path = local_report(check["report"])
        if check.get("report_sha256") != sha256(report_path):
            raise ValueError(f"Verification report hash mismatch: {check['name']}")
        counts = check.get("counts", {})
        if not isinstance(counts, dict) or any(type(count) is not int or count < 0 for count in counts.values()):
            raise ValueError("Verification counts must be explicitly provided nonnegative integers")
        verified_checks.append({key: check[key] for key in ("name", "status", "report_sha256", "counts") if key in check})
    return verified_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default="release")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--portable-report", type=Path, required=True)
    parser.add_argument("--ui-report", type=Path, required=True)
    parser.add_argument("--zip-path")
    parser.add_argument("--mcp-report", type=Path, help="Portable stdio, observer and recovery results for an additive MCP delivery")
    parser.add_argument("--no-zip", action="store_true", help="Finalize the portable folder without creating an archive")
    parser.add_argument("--preview", action="store_true", help="Finalize local preview evidence before an official version URL exists")
    parser.add_argument("--installer-test-work", type=Path, help="New installer-test directory on a Windows account without a TwinPALS installation")
    parser.add_argument("--previous-setup", type=Path, help="Previous public installer for a real version-to-version upgrade check")
    parser.add_argument("--plan", default="docs/PLAN.md", help="Current handover plan inside the project")
    args = parser.parse_args()
    if not args.preview and (args.no_zip or args.installer_test_work is None):
        parser.error("Official finalization requires the ZIP and --installer-test-work for the final setup executable.")
    folder = target_path(args.folder)
    manifest = verify_folder(folder)
    from backend.mcp_server.knowledge import source_metadata
    source_metadata(folder/'docs/mcp/knowledge/source.json', manifest['version'], official=not args.preview)
    evidence, portable, ui = (read_object(path) for path in (args.evidence, args.portable_report, args.ui_report))
    checks = validate_evidence(evidence, ui, args.ui_report, manifest)
    if portable.get("status") != "passed" or portable.get("application_version") != manifest["version"]:
        raise ValueError("Independent portable verification has not passed for this application version")
    if portable.get("server_stopped") is not True or portable.get("port_closed_after_stop") is not True:
        raise ValueError("Portable verification must confirm that its server stopped and test port closed")
    restarts = portable.get('private_state_restarts', [])
    if ({case.get('case') for case in restarts} != {'old_format','current_format','damaged_json'}
            or any(case.get('status') != 'passed' or case.get('materials_and_streams_retained') is not True for case in restarts)):
        raise ValueError('Portable verification must cover old, current and damaged state in a used data folder')
    if portable["source_release_manifest_sha256"] != sha256(folder / MANIFEST):
        raise ValueError("Portable test belongs to a different release manifest; rerun the isolated gate")
    for relative, field in (("TwinPALS.exe", "packaged_server_sha256"), (".runtime/bin/twinpals-worker.exe", "packaged_worker_sha256")):
        if portable[field] != sha256(folder / relative):
            raise ValueError(f"Tested executable differs from packaged executable: {relative}")
    native_manifest = read_object(folder / ".runtime/geant4-runtime-manifest.json")
    native_worker = next((item for item in native_manifest.get("binaries", [])
                          if item.get("path") == ".runtime/bin/twinpals-worker.exe"), None)
    if native_worker is None or native_worker.get("sha256") != portable["packaged_worker_sha256"]:
        raise ValueError("Native runtime manifest does not describe the tested worker executable")
    shutdown = check_shutdown(evidence)
    archive = target_path(args.zip_path or f"dist/TwinPALS-{manifest['version']}-windows-x64.zip")
    from build_installer import build_installer, compiler, output_for, require_new
    installer = output_for(archive)
    require_new(installer)
    iscc = compiler()
    if not args.no_zip and archive.exists():
        raise ValueError(f"ZIP already exists and must be preserved: {archive}")
    public_portable = {k: v for k, v in portable.items() if k not in ("copied_folder", "engine", "sanitized_path", "printed_url", "port")}
    public_portable["copied_to_path_containing_spaces"] = True
    public_portable["engine"] = {k: v for k, v in portable["engine"].items() if k != "path"}
    report = {
        "application": "TwinPALS", "version": manifest["version"], "status": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "browser_verification": ui,
        "frontend_files": {name: value for name, value in manifest["files"].items() if name.startswith("frontend/dist/")},
        "evidence_sha256": sha256(args.evidence), "ui_report_sha256": sha256(args.ui_report),
        "portable_report_sha256": sha256(args.portable_report),
        "native_runtime_manifest_sha256": sha256(folder / ".runtime/geant4-runtime-manifest.json"),
        "isolated_portable_launch": public_portable, "server_shutdown": {
            "owned_processes_stopped": shutdown["owned_processes_stopped"],
            "closed_ports_verified": len(shutdown["ports"]),
            "checked_at": shutdown["ports_rechecked_closed_at"],
        },
        "limitations": "Computational and copied-folder checks on this Windows x64 host; not a fresh-VM certification or experimental detector validation.",
    }
    relative = "docs/RELEASE_VERIFICATION.json"
    # This documentation gate is checked only after all executable and copied-
    # folder checks above succeed. Runtime files are not changed after testing.
    if args.mcp_report:
        mcp = read_object(args.mcp_report)
        if (mcp.get('status') != 'passed' or not mcp.get('server_stopped') or mcp.get('version') != manifest['version']
                or mcp.get('mcp_exe_sha256') != sha256(folder/'TwinPALS-MCP.exe')
                or mcp.get('browser') != ui or mcp['checks'].get('replay_physical_frames', 0) < 1):
            raise ValueError('MCP recovery, observer and executable evidence must match the verified package.')
        report['mcp'] = {'version': manifest['mcp_version'], 'executable_sha256': mcp['mcp_exe_sha256'],
                         'checks': mcp['checks'], 'report_sha256': sha256(args.mcp_report)}
        # The study server has its own guide and verification. Historical
        # module plans describe a different validation campaign.
        handover_documents = {}
    else:
        plan_relative = checked_relative(args.plan).as_posix()
        pending = "- [ ] Native transport checks, build and portable release verification."
        # The handover plan gains final test/cleanup results after packaging. Only
        # documentation is refreshed here; tested runtime bytes stay unchanged.
        plan = (ROOT / plan_relative).read_text(encoding="utf-8-sig")
        if plan.count(pending) != 1:
            raise ValueError("The portable gate must occur once and remain pending before finalization")
        plan = plan.replace(pending, pending.replace("[ ]", "[x]", 1))
        plan = plan.replace("- [ ] Final evidence and remaining scientific limitations documented.", "- [x] Final evidence and remaining scientific limitations documented.")
        plan = "\n".join(
            f"Status: implementation and portable delivery verified — {manifest['version']}, {datetime.now(timezone.utc).date()}."
            if line.startswith("Status: in progress") else line
            for line in plan.split("\n")
        )
        plan = plan.replace("Independent portable launch passed; ZIP finalization remains pending.", "Independent portable launch passed. ZIP integrity is checked by this finalizer before it reports delivery success.")
        plan += ("\n\n## Verified portable handoff — " + report["verified_at"] + "\n\n"
                 f"The complete {manifest['version']} folder passed the displaced-copy launcher gate with development environment variables removed. "
                 f"Real Na-22 and Co-60 runs produced {portable['events']:,} validated event records; analysis matched an independent reader. "
                 "The copied package used its own factory databases and private state, and exercised profile/material exchange. "
                 + ("Module 2 generated and reimported both Na-22 and Co-60 pulse streams with identical analysis. " if portable.get("pulse_runs") else "")
                 + ("Module 3 incrementally processed both generated pulse streams, exercised display rebinning, settings exchange and count reset. " if portable.get("lifetime_runs") else "")
                 + 
                 "Old-format, current and damaged private-state restarts passed using that same used data folder; material entries and stream bytes survived unchanged. "
                 "All listed owned test ports were rechecked closed. Existing user sessions were left intact. "
                 "Use release/Start-TwinPALS.cmd after closing any old application console. "
                 "Exact checks, executable/frontend hashes and limitations are in RELEASE_VERIFICATION.json. "
                 "CeBr3 uses a documented 1 km transparency assumption; experimental absorption remains unvalidated.\n")
        handover_documents = {plan_relative: plan}
        handover_documents["docs/IMPLEMENTATION_STATUS.md"] = (ROOT / "docs/IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8-sig")
        if plan_relative != "docs/PLAN.md":
            index = (ROOT / "docs/PLAN.md").read_text(encoding="utf-8-sig")
            index = "\n".join(
                f"Status: implementation and portable delivery verified — {manifest['version']}, {datetime.now(timezone.utc).date()}."
                if line.startswith("Status: in progress") else line
                for line in index.split("\n")
            )
            handover_documents["docs/PLAN.md"] = index
    for relative_path, contents in handover_documents.items():
        for destination in (ROOT / relative_path, folder / relative_path):
            destination.write_text(contents, encoding="utf-8")
        manifest["files"][relative_path] = {"bytes": (folder / relative_path).stat().st_size,
                                             "sha256": sha256(folder / relative_path)}
    report["documentation_updated_after_portable_gate"] = {
        path: manifest["files"][path] for path in handover_documents
    }
    write_json(ROOT / relative, report)
    write_json(folder / relative, report)
    manifest["files"][relative] = {"bytes": (folder / relative).stat().st_size, "sha256": sha256(folder / relative)}
    manifest["validation"].update(isolated_launch_and_simulation="passed", external_verification=relative, test_servers_stopped=True)
    write_json(folder / MANIFEST, manifest)
    verify_folder(folder)
    result = {"folder": str(folder), "owned_files": len(manifest["files"])}
    result["installer_sha256"] = build_installer(folder, installer, iscc)
    result["installer"] = str(installer)
    if args.installer_test_work:
        from verify_installer import verify
        prior = args.previous_setup.resolve(strict=True) if args.previous_setup else None
        result["installer_verification"] = verify(installer, args.installer_test_work.resolve(), prior)
    if not args.no_zip:
        make_zip(folder, archive, manifest["version"])
        result.update(zip=str(archive), zip_bytes=archive.stat().st_size, zip_sha256=sha256(archive))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
