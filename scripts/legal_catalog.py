# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Assemble offline notices from the components present in a frozen TwinPALS build."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sqlite3
import ssl
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import __version__

DATED = "2026-11-24"
GEANT_PAGE = "https://geant4.web.cern.ch/download/11.4.0.html"
GEANT_SOURCE = "https://codeload.github.com/Geant4/geant4/tar.gz/refs/tags/v11.4.0"
GEANT_ARCHIVE = "geant4-v11.4.0.tar.gz"
GEANT_SHA = "f9b8e9913b9b40322a071d8464c9c20151290188f8a34d40d5162084b29c48a8"
DOI = "https://doi.org/10.25972/OPUS-37663"
PROJECT = "Project"
NATIVE = "Transport and physics data"
SCIENCE = "Scientific sources"
PYTHON = "Python runtime"
WEB = "User interfaces"
SYSTEM = "Native runtime"
UPSTREAM = ROOT / "legal/upstream"
G4 = ROOT / ".runtime/geant4-licenses"
LICENSE_FILE = re.compile(r"(?:^|[_-])(licen[cs]e|copying|notice|copyright|authors)(?:$|[._-])", re.I)
PRIVATE_PATH = re.compile(r"(?:[A-Z]:[/\\]+(?:Users|Documents and Settings)[/\\]+(?!Public\b|Default\b)|/(?:Users|home)/[^/\s]+/)", re.I)

def digest(data):
    return hashlib.sha256(data).hexdigest()


def python_components(executable):
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(executable))
    pyz = next(key for key in archive.toc if key.lower().endswith(".pyz"))
    modules = {name.split(".")[0] for name in archive.open_embedded_archive(pyz).toc}
    for path in (executable.parent / "_internal").rglob("*.pyd"):
        modules.add(path.relative_to(executable.parent / "_internal").parts[0].split(".")[0])
    mapping = metadata.packages_distributions()
    names = {name for module in modules for name in mapping.get(module, [])}
    # A namespace module can be frozen without its top-level distribution metadata.
    names.add("pyinstaller")
    return sorted(names, key=str.casefold)


def texts_for_distribution(dist):
    paths = sorted(dist.files or [], key=str)
    entries = []
    seen = set()
    for rel in paths:
        if not LICENSE_FILE.search(rel.name) and not any(
                p in ("licenses", "LICENSES") and ".dist-info" in str(rel) for p in rel.parts):
            continue
        source = Path(dist.locate_file(rel))
        if not source.is_file() or source.suffix.lower() in (".py", ".pyc", ".html", ".json", ".zip"):
            continue
        key = digest(source.read_bytes())
        if key in seen:
            continue
        seen.add(key)
        label = str(rel).replace("\\", "/")
        if ".dist-info/licenses/" in label:
            label = label.split(".dist-info/licenses/", 1)[1]
        entries.append((label, source))
    entries.sort(key=lambda d:(d[0].count("/"), len(d[0]), d[0]))
    return entries


def build(public, executable):
    public.mkdir(parents=True, exist_ok=True)
    texts = public / "texts"
    texts.mkdir(exist_ok=True)
    components = []
    def add(id_, name, version, group, license_, note, url, docs):
        if not docs or (url is not None and not url.startswith("https://")) or any(row["id"] == id_ for row in components):
            raise ValueError(f"Missing license documents, duplicate ID or invalid upstream for {name}")
        documents = []
        for i, (label, source) in enumerate(docs):
            data = Path(source).read_bytes()
            if not data.strip() or data[:32].lower().startswith((b"<!doctype html", b"<html")):
                raise ValueError(f"Unexpected license document for {name}: {label}")
            text = data.decode("utf-8-sig", errors="replace")
            if PRIVATE_PATH.search(text):
                raise ValueError(f"Private filesystem path in {name}: {label}")
            extension = "rtf" if source.suffix.lower() == ".rtf" else "txt"
            filename = f"texts/{id_}-{i+1}.{extension}"
            (public/filename).write_bytes(data)
            documents.append(dict(label=label, file=filename, sha256=digest(data)))
        components.append(dict(id=id_,name=name,version=version,group=group,license=license_,
                               note=note,url=url,documents=documents))

    add("twinpals","TwinPALS 2.0",__version__,PROJECT,"MIT","Copyright © 2026 Danny Petschke. The MIT license covers original TwinPALS code and documentation. The portable physics data and third-party components have individual terms. G4EMLOW 8.8 is restricted to Geant4 and non-commercial use.","https://opensource.org/license/mit",
        [("MIT license",ROOT/"LICENSE"), ("Project notices and scientific credit",ROOT/"NOTICE.md"), ("Software citation",ROOT/"CITATION.cff")])
    add("twinpals-mcp","TwinPALS 2.0 MCP server and observer",__version__,PROJECT,"MIT",
        "TwinPALS implements the Model Context Protocol using JSON-RPC over standard input and output. The local study service, read-only observer, offline methods handbook and shared Windows notification-area helper and icon are original TwinPALS work covered by the project MIT license. The helper uses the Windows-installed .NET Framework and Windows Forms. Their system assemblies are provided by Windows.",
        "https://modelcontextprotocol.io/specification/2025-11-25/basic/transports", [("MIT license",ROOT/"LICENSE")])
    add("inno-setup","Inno Setup","7",SYSTEM,"Inno Setup License",
        "The optional Windows installer and its uninstaller are built with Inno Setup by Jordan Russell and Martijn Laan.",
        "https://jrsoftware.org/isinfo.php",[("Original license",ROOT/"native/windows/installer/Inno-Setup-license.txt")])
    add("data","Optical curves and catalogue data","",SCIENCE,"Source-specific terms",
        "Open Database, select a material or instrument, and consult its references for the source, units and assumptions of each property. Permissions for redistribution depend on that source.",
        None,[("Project notices",ROOT/"NOTICE.md")])
    add("geant4","Geant4","11.4.0",NATIVE,"Geant4 Software License","This product includes software developed by Members of the Geant4 Collaboration (http://cern.ch/geant4).",GEANT_PAGE,[("Geant4 license",G4/"Geant4-LICENSE.txt")])
    add("clhep","CLHEP","Geant4 11.4.0 edition",NATIVE,"LGPL-3.0","The replaceable G4clhep.dll is supplied with the original build source in legal/sources/geant4-v11.4.0.tar.gz. The source archive contains the CMake build system and source/externals/clhep.", "https://github.com/Geant4/geant4/tree/v11.4.0/source/externals/clhep",[("GNU Lesser General Public License, version 3",G4/"CLHEP-COPYING.LESSER.txt"),("GNU General Public License, version 3",G4/"CLHEP-LICENSE.txt")])
    for key, name, text, license_ in (("ptl","PTL","PTL-LICENSE.txt","MIT"), ("expat","Expat","Expat-COPYING.txt","MIT"),("zlib","zlib","zlib-LICENSE.txt","Zlib"),("g4tools","G4tools","G4tools-LICENSE.txt","Component-specific upstream terms")):
        add(key,name,"Geant4 11.4.0 edition",NATIVE,license_,"Bundled with the Geant4 runtime. The accompanying text preserves upstream copyright and redistribution terms.",GEANT_PAGE,[("Original notice",G4/text)])
    add("nlohmann","JSON for Modern C++","3.11.3",NATIVE,"MIT","Used in the native calculation and transport workers.","https://github.com/nlohmann/json/tree/v3.11.3",[("Vendored header license",ROOT/"native/vendor/LICENSE.nlohmann-json"),("Geant4 notice",G4/"nlohmann-json-LICENSE.txt")])
    for key, name, ver, text, rights, note in (
        ("emlow","G4EMLOW","8.8",G4/"G4EMLOW8.8-README.txt","Non-commercial · Geant4 only","The original upstream data notice restricts use to Geant4 and excludes commercial use."),
        ("ensdf","G4ENSDFSTATE","3.0",G4/"G4ENSDFSTATE3.0-README.txt","Upstream data notice","Nuclear state data derived from ENSDF. The original distribution records data provenance."),
        ("photon","PhotonEvaporation","6.1.2",G4/"PhotonEvaporation6.1.2-README.txt","Upstream data notice","Nuclear level and transition data distributed for Geant4."),
        ("surface","RealSurface","2.2",ROOT/".runtime/geant4-data/RealSurface2.2/README","Upstream data notice","Optical surface measurements from LBNL and UC Davis. The original distribution describes the measurement sets.")):
        add(key,name,ver,NATIVE,rights,note,GEANT_PAGE,[("Original dataset README",text)])
    lock = json.loads((ROOT/"frontend/package-lock.json").read_text(encoding="utf-8"))["packages"]
    for relative, row in sorted(lock.items()):
        if not relative or row.get("dev"): continue
        name = relative.rsplit("node_modules/",1)[-1]
        base = ROOT/"frontend"/relative
        files = [(p.name,p) for p in sorted(base.iterdir()) if p.is_file() and LICENSE_FILE.search(p.name)]
        license_ = row.get("license","Original notice")
        if name == "lucide-react":
            files.append(("Feather MIT license",UPSTREAM/"Feather-MIT.txt"))
            license_ = "ISC and MIT (Feather)"
        add("web-"+re.sub(r"[^a-z0-9-]","-",name),name,row["version"],WEB,license_,"Included in the offline user interfaces.","https://www.npmjs.com/package/"+name,files)
    add("cpython","CPython",sys.version.split()[0],PYTHON,"PSF and incorporated licenses","Python interpreter, standard library and incorporated third-party code.","https://docs.python.org/3.12/license.html",[("Python license",Path(sys.base_prefix)/"LICENSE.txt"),("Incorporated software notices",UPSTREAM/"CPython-incorporated.rst"),("bzip2 license",UPSTREAM/"bzip2-LICENSE.txt"),("XZ and liblzma notices",UPSTREAM/"XZ-COPYING.txt")])
    fallback = {"certifi":"MPL-2.0","pyinstaller":"GPL-2.0-or-later with bootloader exception","h11":"MIT","httpx":"BSD-3-Clause","tzdata":"Apache-2.0 and IANA data terms","psutil":"BSD-3-Clause","colorama":"BSD-3-Clause","pyyaml":"MIT"}
    for name in python_components(executable):
        dist = metadata.distribution(name)
        canonical = dist.metadata["Name"]
        key = canonical.casefold().replace("_","-")
        files = texts_for_distribution(dist)
        if key == "numpy":
            files.insert(0, ("NumPy wheel and bundled BLAS / compiler runtime notices",Path(dist.locate_file(f"numpy-{dist.version}.dist-info/licenses/LICENSE.txt"))))
            files = [entry for i,entry in enumerate(files) if i == 0 or entry[1]!=files[0][1]]
            files.append(("Native random distributions",ROOT/"native/vendor/LICENSE.numpy-random"))
        note = "Included in the portable Python application."
        if key == "pyinstaller": note="The frozen launchers use the PyInstaller bootloader. The original license includes the bootloader exception."
        if key == "certifi":
            files.append(("Mozilla Public License, version 2.0",UPSTREAM/"MPL-2.0.txt"))
            note="The unmodified Mozilla CA bundle is also supplied in readable source form under _internal/certifi/cacert.pem."
        if key == "pyyaml":
            files.append(("LibYAML native parser license",UPSTREAM/"libyaml-LICENSE.txt"))
        if key == "pydantic-core":
            if dist.version != "2.50.1":
                raise ValueError("Refresh the Rust notice collection for the new pydantic-core version.")
            files.append(("Rust dependency notices and archive identities",UPSTREAM/"Pydantic-Core-Rust-notices.txt"))
            note="Native Python validation extension. The Rust notice collection covers the matching upstream lockfile, including optional and build dependencies."
        license_ = dist.metadata.get("License-Expression") or fallback.get(key,"See original license")
        add("python-"+key,canonical,dist.version,PYTHON,license_,note,"https://pypi.org/project/"+canonical+"/"+dist.version+"/",files)
    for key,name,version,license_,url,files in (
        ("openssl","OpenSSL",ssl.OPENSSL_VERSION.split()[1],"Apache-2.0","https://www.openssl.org/",[("OpenSSL license",UPSTREAM/"OpenSSL-LICENSE.txt")]),
        ("libffi","libffi","Windows Python runtime","MIT","https://github.com/libffi/libffi",[("Original notice",UPSTREAM/"libffi-LICENSE.txt")]),
        ("sqlite","SQLite",sqlite3.sqlite_version,"Public domain","https://sqlite.org/copyright.html",[("Public-domain dedication",UPSTREAM/"SQLite-dedication.md")]),
        ("tcltk","Tcl and Tk","8.6","Tcl/Tk licenses","https://www.tcl-lang.org/software/tcltk/license.html",[("Tcl license",UPSTREAM/"Tcl-license.terms"),("Tk license",Path(sys.base_prefix)/"tcl/tk8.6/license.terms")]),
        ("msvc","Microsoft Visual C++ and Universal CRT","Windows x64","Microsoft redistribution terms","https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution",[("Runtime terms (plain text)",UPSTREAM/"Microsoft-VC-Runtime.txt"),("Original runtime terms (RTF)",UPSTREAM/"Microsoft-VC-Runtime.rtf"),("Visual Studio redistributable list",UPSTREAM/"Microsoft-VS2022-Redist.txt")])):
        add(key,name,version,SYSTEM,license_,"Native runtime supplied with the Windows distribution.",url,files)
    expected = {d["file"] for c in components for d in c["documents"]}
    # The public tree is exclusively generated. Refuse unknown files instead of publishing them.
    extra = {p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()} - expected - {"index.json"}
    if extra: raise ValueError(f"Unexpected files in the public notice tree: {sorted(extra)}")
    (public/"index.json").write_text(json.dumps(dict(version=__version__,reviewed=DATED,components=components),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return components


def copy_corresponding_source(dest):
    src = ROOT/".runtime/legal-sources"/GEANT_ARCHIVE
    if not src.is_file() or digest(src.read_bytes()) != GEANT_SHA:
        raise ValueError("Provide the pinned Geant4 source archive from "+GEANT_SOURCE+" under .runtime/legal-sources/. Expected SHA-256 "+GEANT_SHA)
    with tarfile.open(src) as archive:
        for path in ("source/externals/clhep/CMakeLists.txt","CMakeLists.txt","LICENSE"):
            archive.getmember("geant4-11.4.0/"+path)
    dest.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src, dest/GEANT_ARCHIVE)
    (dest/"SHA256SUMS.txt").write_text(GEANT_SHA+"  "+GEANT_ARCHIVE+"\n",encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows=build(args.out,args.exe)
    print(f"{len(rows)} components and {sum(len(row['documents']) for row in rows)} source notices")

