# Third-party materials

The footer catalog in both TwinPALS applications reads `legal/public/index.json`. Each entry identifies the component, version or distribution, upstream reference, license description, and local original documents. SHA-256 values identify the bytes of each document. The development checkout and portable build use the same catalog format.

| Material | Source and handling |
| --- | --- |
| Geant4, PTL, CLHEP, Expat, zlib and G4tools | Original license texts from the pinned Geant4 11.4.0 distribution. The Windows package provides CLHEP as the separately replaceable `G4clhep.dll` beside the worker. The matching source archive and CMake files are under `legal/sources`. [Geant4 release](https://geant4.web.cern.ch/download/11.4.0.html) |
| Geant4 data | Read each dataset's original README. G4EMLOW 8.8 explicitly restricts use to Geant4 and excludes commercial use. RealSurface, PhotonEvaporation and ENSDFSTATE have individual provenance. [Geant4 dataset distribution](https://geant4.web.cern.ch/download/11.4.0.html) |
| Native random distributions and JSON | Preserve the NumPy and Melissa E. O’Neill notices and the vendored JSON license. NumPy's wheel includes the BLAS implementation and compiler runtime notices. [NumPy](https://numpy.org/doc/stable/license.html) · [JSON for Modern C++](https://github.com/nlohmann/json) |
| Python packages | The catalog builder reads import names from the actual frozen PYZ and Python extensions, maps them to installed distributions, and copies their original documents. PyInstaller supplies the bootloader with a distribution exception. [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |
| Rust, compression and CA certificates | The Pydantic Core entry includes the 99 registry archives pinned in its 2.50.1 source lockfile. Shared copies of a license text are indexed by hash. The CPython entry includes bzip2 and XZ notices. PyYAML includes the native LibYAML notice. Certifi includes the full Mozilla Public License 2.0. [Pydantic Core source release](https://pypi.org/project/pydantic-core/2.50.1/#files) · [Mozilla Public License](https://www.mozilla.org/MPL/2.0/) |
| CPython and native libraries | The interpreter license and incorporated notices accompany the native dependencies. Tcl/Tk 8.6.12, libffi, SQLite and OpenSSL have their own entries. [CPython 3.12.14](https://github.com/python/cpython/blob/v3.12.14/Doc/license.rst) · [Tcl](https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms) · [libffi](https://github.com/libffi/libffi/blob/v3.4.4/LICENSE) · [SQLite](https://sqlite.org/copyright.html) · [OpenSSL](https://github.com/openssl/openssl/blob/openssl-3.5.8/LICENSE.txt) |
| Microsoft runtime | The original Visual C++ 2015–2022 runtime terms, a plain-text rendering and the Microsoft redistribution notice accompany the Windows build. Microsoft determines which binaries a licensed distributor may redistribute. [Microsoft redistributable list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution) |
| Frontend | Production entries in the npm lockfile supply the software versions. Each installed package supplies its notice. Lucide credits Feather, whose MIT license is included separately. [Feather license](https://github.com/feathericons/feather/blob/v4.29.2/LICENSE) |
| Scientific basis | Dominik Boras’ 2024 dissertation provides the conceptual foundation for TwinPALS. [Dissertation](https://doi.org/10.25972/OPUS-37663) |
| Catalogue data | Consult the references attached to each material, curve or device for its origin, assumptions and applicable permissions. |
| MCP server and observer | TwinPALS implements the stdio protocol in its own MIT-licensed code. The desktop and observer both expose the shared offline license catalog. [Protocol specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) |

To regenerate the catalog for a new build, use `scripts/legal_catalog.py` with the frozen executable from that build. Inspect upstream changes before redistributing. The source snapshot contains original project code and publishable notices. To prepare the repository use `scripts/public_source.py` and extract the resulting archive into a clean directory. The research binary includes separately licensed source data and runtimes.

## Windows notification area and product icons

TwinPALS.Tray.exe uses the original TwinPALS SVG mark. Its Windows icon contains rasterizations of the same artwork used in both browser interfaces. The helper and artwork are covered by the project MIT license. The helper calls Windows Forms and drawing APIs supplied by the installed Windows .NET Framework. [Microsoft Windows Forms NotifyIcon documentation](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon?view=netframework-4.8.1)

Copyright © 2026 Danny Petschke · twinpals@proton.me

