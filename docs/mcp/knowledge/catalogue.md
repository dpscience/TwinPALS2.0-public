# Detector catalogue, units and source evidence

The shared SQLite catalogue stores instruments, optical materials, response curves, source references and recorded model assumptions. A missing database is initialized from the bundled factory data. A saved catalogue is opened on subsequent starts. Current entries describe available components; a recorded stream or completed study preserves its own configuration.

Find comparable devices with catalogue_list, then read the complete record with catalogue_get. For a new PMT, check cathode dimensions and shape, window optics, gain and reference bias, pulse rise, transit time, transit-time spread, response curves, units and source conditions. Rise time, transit time and transit-time spread represent different physical quantities. Distinguish the datasheet's spread convention, such as FWHM, from a model sigma.

For a catalogue change, identify the exact device and variant. Preserve manufacturer citations and state any permitted estimate directly with the property. Supply expected_revision for an update, then read back the saved revision. Cite the entry's own source for a numeric property. The Boras dissertation is the scientific basis of TwinPALS; individual curves have their own provenance.

Example. When a window thickness is an assumption, disclose its value and rationale in the entry and methods. Include a sensitivity comparison if that assumption changes the study conclusion.

