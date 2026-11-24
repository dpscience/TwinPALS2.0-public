# TwinPALS 2.0

**Cite this software** · Danny Petschke, *TwinPALS 2.0*, version 2.0.0. When publishing results, please also cite Dominik Boras’s 2024 doctoral dissertation on the PALS digital twin. [Software citation (CITATION.cff)](CITATION.cff) · [Dissertation (DOI)](https://doi.org/10.25972/OPUS-37663)

TwinPALS simulates positron annihilation lifetime spectroscopy (PALS) on Windows x64. Set up a detector, acquire digitized pulse pairs and see how timing, filters and event selection affect the lifetime spectrum. The desktop and MCP server share the same simulation engines and component catalogue.

[![Na-22 simulation with particle tracks in the detector assembly and the resulting anode current](docs/screenshots/detector-transport.png)](docs/screenshots/detector-transport.png)

| Digitizer setup | Waveform acquisition | Lifetime analysis |
| :--- | :--- | :--- |
| [![Two PMT channels connected to a digitizer and coincidence trigger](docs/screenshots/acquisition-chain.png)](docs/screenshots/acquisition-chain.png) | [![Digitized pulses and trigger timing for channels A and B](docs/screenshots/waveform-acquisition.png)](docs/screenshots/waveform-acquisition.png) | [![Lifetime and pulse-height spectra before and after filtering](docs/screenshots/lifetime-analysis.png)](docs/screenshots/lifetime-analysis.png) |

## Run the desktop

Download a Windows x64 build from [Releases](https://github.com/dpscience/TwinPALS2.0-public/releases). Run **TwinPALS-…-setup.exe** for a Start menu entry and automatic reuse of your catalogue on updates. For a portable copy, extract the **entire ZIP** to a writable folder and open **TwinPALS.exe**. Both include the scientific runtime. The tray icon reopens the workbench.

## Connect an MCP client

In PowerShell, open the program folder (by default `%LOCALAPPDATA%\Programs\TwinPALS 2.0` for Setup) or the extracted portable folder and print the configuration for your client.

```powershell
.\TwinPALS-MCP.exe --print-config claude-desktop
```

Replace `claude-desktop` with `codex`, `claude-code`, `copilot-cli` or `vscode` as appropriate. Add the printed entry to the client's MCP configuration, reconnect and ask it to call **capabilities**. The client starts the local server. Choose **Open study observer** in the tray to follow its work. [Client configuration and study examples](docs/mcp/README.md)

## Build from source

On Windows x64 with Python 3.12, Node.js/npm, CMake and Visual Studio 2022 C++ tools, run this from the repository root.

```powershell
.\scripts\build-workbench.ps1
.\Start-TwinPALS.cmd
```

Both factory tables are included. The source build fetches the pinned Geant4 SDK and physics data once and caches them. The portable application already includes its runtime and datasets. [Build steps, tests and portable packaging](docs/BUILD.md)

| Directory | Start here |
| --- | --- |
| `backend/` | Desktop launcher, local API, catalogue and module processing |
| `backend/mcp_server/` | MCP tools, persistent studies and the observer service |
| `frontend/src/` | React workbench, plots and observer |
| `native/` | Geant4 worker, pulse processing libraries and Windows tray |
| `seed/` and `third_party/geant4/` | Factory catalogue, material definitions and Geant4 dependency manifest |
| `tests/` and `frontend/tests/` | Python and frontend checks |

Original TwinPALS code is MIT-licensed. Catalogue entries record their sources. The bundled G4EMLOW data are for non-commercial use within Geant4. This product includes software developed by Members of the Geant4 Collaboration (http://cern.ch/geant4). [Notices](NOTICE.md) · [Scientific basis and citation](CITATION.cff)
