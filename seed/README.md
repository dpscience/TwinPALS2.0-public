# Factory catalogue

`factory_catalogue.json` supplies the initial TwinPALS catalogue, including materials, photomultipliers and digitizers. When `data/catalogue.tpdb` is missing, TwinPALS creates this SQLite database from the factory catalogue at startup. Later starts open the existing database, including edits made in the Database tab. `geant4_materials.json` provides the standard material compositions and densities for the bundled Geant4 version.

Both source repositories include the complete factory catalogue and Geant4 material table. Local measurements, editable databases and studies belong in the application's data directory.

Each optical curve records its source and assumptions. Manufacturer and research tables carry source-specific rights. The scientific basis is the doctoral dissertation of Dominik Boras (2024). [Dissertation](https://doi.org/10.25972/OPUS-37663)

The source build restores its pinned Geant4 SDK and datasets from the verified build cache. See the [Windows build instructions](../docs/BUILD.md).
