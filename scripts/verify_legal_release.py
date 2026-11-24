# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Verify both the off-line public catalog and the packaged desktop footer."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid

from legal_catalog import DOI, GEANT_ARCHIVE, GEANT_SHA, PRIVATE_PATH, ROOT
from package_release import sha256, version

HTTP = build_opener(ProxyHandler({}))


def audit(folder):
    public = folder/"legal/public"
    catalog = json.loads((public/"index.json").read_text(encoding="utf-8"))
    assert (folder/"VERSION.txt").read_text().strip()==catalog["version"]==version()
    docs = {"index.json"}
    ids = set()
    for component in catalog["components"]:
        assert component["id"] not in ids and component["documents"]
        assert component["url"] is None if component["id"] == "data" else component["url"].startswith("https://")
        ids.add(component["id"])
        for doc in component["documents"]:
            parts=PurePosixPath(doc["file"]).parts
            assert len(parts)==2 and parts[0]=="texts" and ".." not in parts
            assert doc["file"] not in docs
            docs.add(doc["file"])
            assert sha256(public/doc["file"])==doc["sha256"]
    assert docs=={p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()}
    assert {"geant4","emlow","clhep","surface","cpython","python-numpy","web-react","web-three","msvc","twinpals","twinpals-mcp","inno-setup"} <= ids
    assert sha256(folder/"legal/sources"/GEANT_ARCHIVE)==GEANT_SHA
    for name in ("LICENSE","NOTICE.md","CITATION.cff"):
        assert (folder/name).read_bytes()==(ROOT/name).read_bytes()
    assert DOI in (folder/"CITATION.cff").read_text(encoding="utf-8")
    manifest=json.loads((folder/"release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"]==manifest["mcp_version"]==version()
    assert all(not n.startswith(("tmp/","research/","history/","validation/","data/")) for n in manifest["files"])
    checked_texts=0
    for name in [*manifest["files"],"release-manifest.json"]:
        path=folder/name
        portable_text = (name.startswith(("legal/public/","docs/","seed/","frontend/dist/"))
                         or PurePosixPath(name).parent == PurePosixPath(".")
                         or name in (".runtime/geant4-env.json",".runtime/geant4-runtime-manifest.json","legal/UPSTREAM.md"))
        if portable_text and path.suffix.lower() not in (".exe",".dll",".gz",".png",".rtf"):
            content=path.read_text(encoding="utf-8-sig",errors="replace")
            if PRIVATE_PATH.search(content):
                raise AssertionError("Private filesystem path in "+name)
            checked_texts+=1
    # PyInstaller compiles Python with embedded code filenames. Verify our frozen modules as well.
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(folder/"TwinPALS.exe"))
    pyz=archive.open_embedded_archive(next(k for k in archive.toc if k.endswith(".pyz")))
    owned=[k for k in pyz.toc if k=="backend" or k.startswith("backend.")]
    assert "backend.mcp_server.cli" in owned
    assert not any(k.split(".")[0] in {"mcp","fastmcp"} for k in pyz.toc)
    assert "tkinter.filedialog" in pyz.toc
    assert all((folder/"_internal"/name).is_file() for name in ("_tkinter.pyd","_tcl_data/init.tcl","_tk_data/tk.tcl"))
    assert owned
    for key in owned:
        file=pyz.extract(key).co_filename
        assert not Path(file).is_absolute() and not PRIVATE_PATH.search(file), key
    local_root=str(ROOT)
    for name in ("TwinPALS.exe","TwinPALS-MCP.exe",".runtime/bin/twinpals-worker.exe",
                 ".runtime/bin/twinpals-analog.dll",".runtime/bin/twinpals-lifetime.dll",".runtime/bin/twinpals-sweeps.dll"):
        raw=(folder/name).read_bytes().lower()
        for spelling in (local_root,local_root.replace("\\","/")):
            assert spelling.casefold().encode() not in raw and spelling.casefold().encode("utf-16-le") not in raw,name
    return catalog,docs,dict(components=len(ids),original_documents=len(docs)-1,frozen_modules=len(owned),public_files_checked=checked_texts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True,type=Path)
    parser.add_argument("--report",required=True,type=Path)
    args=parser.parse_args()
    folder=args.folder.resolve()
    report=args.report.resolve()
    report.parent.mkdir(parents=True,exist_ok=True)
    catalog,docs,findings=audit(folder)
    with closing(socket.socket()) as listener:
        listener.bind(("127.0.0.1",0))
        port=listener.getsockname()[1]
    url=f"http://127.0.0.1:{port}"
    env={k:v for k,v in os.environ.items() if not k.startswith(("PYTHON","TWINPALS","G4","GEANT4"))}
    local=report.parent/("desktop-"+uuid.uuid4().hex)
    process=subprocess.Popen([str(folder/"TwinPALS.exe"),"--no-browser","--port",str(port),"--data-dir",str(local)],
                              env=env,cwd=local.parent,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    try:
        for attempt in range(160):
            try:
                with HTTP.open(url+"/api/health",timeout=2) as response:
                    assert json.load(response)["version"]==catalog["version"]
                break
            except URLError:
                if process.poll() is not None or attempt==159: raise
                time.sleep(.25)
        for name in sorted(docs):
            with HTTP.open(url+"/legal/"+name,timeout=10) as response:
                assert hashlib.sha256(response.read()).hexdigest()==sha256(folder/"legal/public"/name)
        ui=report.parent/"desktop-browser.json"
        subprocess.run([shutil.which("node") or "node",str(ROOT/"scripts/verify_mcp_ui.cjs"),str(ui),"--licenses"],
                       input=url,cwd=ROOT,text=True,check=True,timeout=90)
        browser=json.loads(ui.read_text(encoding="utf-8"))
        assert browser["ok"] and len(browser["licenses"])>=6
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=20)
    with closing(socket.socket()) as listener:
        assert listener.connect_ex(("127.0.0.1",port)) != 0
    report.write_text(json.dumps(dict(status="passed",version=catalog["version"],**findings,port=port,
        asset_hash=sha256(folder/"legal/public/index.json"),desktop_checks=browser["licenses"],server_stopped=True),indent=2)+"\n",
        encoding="utf-8")
    print(report.read_text(encoding="utf-8"))


if __name__=="__main__":
    main()

