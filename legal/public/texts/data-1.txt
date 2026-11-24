# TwinPALS 2.0

Copyright © 2026 Danny Petschke. Contact **twinpals@proton.me**. Project version **2.0.0**, pre-release. Notices reviewed 24 November 2026.

## Scientific basis

TwinPALS 2.0 builds on the digital-twin approach described by Dominik Boras in his 2024 doctoral dissertation at Julius-Maximilians-Universität Würzburg, *Digitale Positronen-Annihilation-Lebensdauer-Spektroskopie: Geant4-Monte-Carlo-Simulation und Puls-Generator-Kopplung für einen realitätsgetreuen digitalen Zwilling*. Please cite the dissertation alongside TwinPALS when publishing results. The machine-readable citation is in `CITATION.cff`. [Dissertation and bibliographic record](https://doi.org/10.25972/OPUS-37663)

## Software and third-party materials

The optional Windows installer and uninstaller use Inno Setup by Jordan Russell and Martijn Laan. Its original license is supplied in the installer sources and installed legal materials. The Windows tray uses the system .NET Framework. Setup requests consent before retrieving a missing runtime directly from Microsoft. [Inno Setup](https://jrsoftware.org/isinfo.php)

The MIT license in `LICENSE` covers original TwinPALS source and documentation by Danny Petschke. Upstream code, datasets, libraries, illustrations, and manufacturer material retain their own terms. The scientific citation above is an attribution request. The MIT permission grant is reproduced in full in the license file.

This product includes software developed by Members of the Geant4 Collaboration (http://cern.ch/geant4). The portable installation includes Geant4 and separately licensed data. The G4EMLOW 8.8 notice restricts its use to Geant4 and excludes commercial use. Preserve its notice when sharing the installation. [Geant4 license](https://geant4.web.cern.ch/download/license.html)

TwinPALS implements its own Model Context Protocol (MCP) server using JSON-RPC over standard input and output. The MIT license covers the server, local study service and observer. The shared catalog lists the components distributed with both applications.

The TwinPALS 2.0 database records the source and assumptions for individual optical curves and instrument properties. Consult each entry for its references and the applicable permissions when redistributing its data.

Open **Third-party licenses** in the footer of either interface to read the component notices offline. The portable installation also provides the index and the original texts under `legal/`. The Geant4 source used for the bundled CLHEP library is available alongside the legal materials in the portable folder.
