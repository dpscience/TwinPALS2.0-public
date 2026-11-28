# Factory catalogue

`factory_catalogue.json` supplies the initial TwinPALS catalogue, including materials, photomultipliers and digitizers. When `data/catalogue.tpdb` is missing, TwinPALS creates this SQLite database from the factory catalogue at startup. Later starts open the existing database, including edits made in the Database tab. `geant4_materials.json` provides the standard material compositions and densities for the bundled Geant4 version.

Both source repositories include the complete factory catalogue and Geant4 material table. Local measurements, editable databases and studies belong in the application's data directory.

Each optical curve records its source and assumptions. Manufacturer and research tables carry source-specific rights. The scientific basis is the doctoral dissertation of Dominik Boras (2024). [Dissertation](https://doi.org/10.25972/OPUS-37663)

The source build restores its pinned Geant4 SDK and datasets from the verified build cache. See the [Windows build instructions](../docs/BUILD.md).

## Updating an installed catalogue

Append a release to `factory_updates` when shipping new IDs or fields. Compare with the previous published seed. List newly introduced IDs separately and name the existing IDs receiving each new property or curve. Keep prior release records in order. A fresh installation records the included releases. Desktop and MCP apply pending releases once, in a SQLite transaction. The migration copies the referenced fields for matching model IDs, including locally edited factory models. Missing older IDs or fields represent local removals. Custom film or QE changes can be reviewed in the Photocathode tab.
