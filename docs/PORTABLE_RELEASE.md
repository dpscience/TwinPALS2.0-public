# Windows distribution

Keep the desktop application and study server together in the extracted folder. Open **Third-party licenses** in either footer to read the offline notices.

## Build

Explorer launches use the TwinPALS notification-area menu. A single icon serves the desktop and the MCP coordinator in the signed-in Windows session. **Status and paths** identifies the database and executable for each service. The build compiles the original tray helper with the Windows .NET Framework 4.x x64 C# compiler. Windows supplies its runtime assemblies.

Build the frontend with `npm ci` and `npm run build` in `frontend`. Install the Python requirements in the project virtual environment. Build the pinned Geant4 11.4.0 worker with `scripts/build-native.ps1`. The worker obtains the project version from `backend/__init__.py`.

The [Windows source build](BUILD.md) prepares the licensed runtime, factory catalogue, original physics datasets and corresponding Geant4 source using the included catalogues and the verified build cache. The resulting portable folder includes the required DLLs and datasets and starts without the cache or a network connection. The packager verifies the source archive before adding it to the distribution.

```powershell
.venv\Scripts\python.exe scripts/package_release.py --output tmp/candidate --zip-path tmp/candidate-assets/TwinPALS-windows-x64.zip --no-zip
.venv\Scripts\python.exe scripts/verify_portable.py --source tmp/candidate --report tmp/portable-check.json
.venv\Scripts\python.exe scripts/verify_mcp.py --exe tmp/candidate/TwinPALS-MCP.exe --browser --report tmp/mcp-check.json
.venv\Scripts\python.exe scripts/verify_windows_tray.py --folder tmp/candidate --report tmp/tray-check/results.json
```

The build inventories frozen Python modules, native wheels, frontend production dependencies, Geant4 libraries and datasets. It copies their original notices and the corresponding Geant4 source into the portable folder. Both interfaces serve the same local catalog. Upstream websites are optional reference links.

## Data and updates

The portable ZIP contains a freshly initialized factory database. If `data/catalogue.tpdb` is absent when you start `TwinPALS.exe`, the application creates it from `seed/factory_catalogue.json`. Subsequent starts open your saved database. Installation updates replace files owned by the package manifest and preserve user databases, settings, studies and measurement streams. Keep the previous verified package for rollback.

## Publication

### Installed layout

On first installation, choose a program folder or accept `%LOCALAPPDATA%\Programs\TwinPALS 2.0`. A newer installer updates the existing folder in place. Rerun the same version to repair or uninstall. Both executables use `%LOCALAPPDATA%\TwinPALS\Data` by default. Repair and update preserve its contents.

During interactive uninstall, **Keep my data** preserves the catalogue, settings, runs and studies for reinstallation. **Choose data to delete** lists the full paths before removal. You can add another dedicated TwinPALS workspace. Confirming removal deletes all contents of the listed folders. Silent uninstall keeps data. For backup or transfer, stop both services and copy the data folder and externally stored runs. Use `--data-dir` to select an existing workspace. Keep the portable copy and installed program in separate directories.

Close active desktop and study services through the tray before updating. Install a newer setup over the existing installation. Setup checks for the Windows .NET Framework used by the tray. If it is missing, interactive Setup offers to download the verified Microsoft installer. Silent setup reports the missing prerequisite. Python, Node.js and Geant4 are bundled for end users.

### Release assets

Verify the final versioned ZIP and setup EXE, their SHA-256 sidecars and the setup lifecycle before attaching all four files to the GitHub Release for the public tag. Use a new output basename when finalizing a previously built candidate. Keep binaries out of Git source history.

If the build account already has TwinPALS installed, run the finalizer with `--stage-for-installer-qa`. Upload the four files to a draft release. The **Windows installer lifecycle** workflow tests its installer and the preceding official installer on a fresh Windows runner. Check that the receipt reports success and both SHA-256 values match the release assets before publishing the draft.

Before each public build, record the confirmed repository URL and the exact GitHub release URL for its version in `docs/mcp/knowledge/source.json`. Build with `--public-release`. Both the portable distribution and installer must contain this file. The official finalizer checks the packaged metadata and requires the version-specific release tag. Use `--preview` only for a local preview. After publishing, verify the link, tagged revision and downloadable files anonymously.

The source checkout includes the reviewed product sources, both factory tables, the Geant4 bundle and original notices. Catalogue entries retain their individual references and assumptions. [Project rights and scientific credit](../NOTICE.md)

A copied-folder Windows test covers local execution and stream exchange. It verifies software behaviour on the test host. Experimental agreement requires a separate instrument comparison.

TwinPALS 2.0 · © 2026 Danny Petschke · twinpals@proton.me. Scientific basis · Dominik Boras (2024), Universität Würzburg. [Dissertation](https://doi.org/10.25972/OPUS-37663)
