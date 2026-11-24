# Build TwinPALS on Windows x64

For the ready-to-run application, extract the Windows portable ZIP and launch `TwinPALS.exe`. These instructions are for building your own copy.

Install x64 CPython 3.12 with the Windows launcher, pip and Tcl/Tk, Node.js 22 with npm, CMake and Visual Studio 2022 with **Desktop development with C++** and a Windows SDK. Use a writable checkout. Python and npm fetch their pinned dependencies on the first build. Both catalogue files are included. The first build downloads six pinned Geant4 archives and verifies their SHA-256. Later builds reuse the cache under `%LOCALAPPDATA%/TwinPALS/build-cache/geant4`.

```powershell
.\scripts\build-workbench.ps1
.\Start-TwinPALS.cmd
```

To share or prefill a cache, pass `-Geant4Cache D:\BuildCache\Geant4`. Pass `-OfflineGeant4` to require the six verified archives locally. This option covers Geant4. Python and npm also need installed or cached dependencies for a fully disconnected build. Neither the portable desktop nor the packaged MCP server uses this cache.

The script creates `.venv`, installs dependencies, builds the frontend, unpacks verified archives into `.runtime`, compiles the native worker and libraries, and audits the DLL imports. It can be run again after an interrupted build. For the source MCP entry point use `.venv\Scripts\python.exe scripts/start_mcp.py --help`.

## Verify and package

```powershell
npm --prefix frontend test
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/package_release.py --output release
```

Install [Inno Setup 7](https://jrsoftware.org/isinfo.php) before packaging. The packager finds a per-user or machine installation, or accepts the compiler path in `TWINPALS_ISCC`. It builds both launchers and the tray helper, verifies the portable folder, and creates a versioned ZIP and a sibling `-setup.exe` with SHA-256 files. Use a fresh `--zip-path` for each candidate. Even a folder-only build with `--no-zip` creates its installer. The public wizard, artwork and license are under `native/windows/installer/`. To verify the portable folder later, use `scripts/package_release.py --verify-folder release`.

## Source and data

The two stream boundaries are documented in the [detector stream format](STREAM_FORMAT.md) and the [digitizer stream format](MODULE2_STREAM.md). The [MCP guide](mcp/README.md) describes the same engines through the study API. Build inputs and their terms are listed in the [Geant4 bundle](../third_party/geant4/README.md) and [project notices](../NOTICE.md).
