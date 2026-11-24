# TwinPALS study map

The desktop and study observer can check the latest stable TwinPALS release on GitHub after startup. The version control in the footer offers a manual check and automatic-check preferences. The MCP `capabilities` tool reports the installed version and cached release information without contacting GitHub or interrupting a study.

A measurement connects three different objects. Module 1 produces detector responses to simulated gamma emissions. Module 2 combines responses on a source clock and records triggered pairs of digitized waveforms. Module 3 measures those samples and builds pulse-height and lifetime spectra.

| Question | Evidence to retrieve |
| --- | --- |
| What can I change? | Use `profile_get` with `schema_only=true` for the module and inspect the corresponding profile. |
| Which instrument values did the simulation use? | Read the saved profile and stream header. Retrieve device curves, assumptions and source references with `catalogue_get`. |
| How did a peak enter a spectrum? | Follow the PHS window, optional filters, time direction and contributor class described in the pulse, contributions and spectra chapters. |
| What happened in this particular experiment? | Read `study_status`, then `run_result` for the attempt and inspect its metrics, inputs and outputs. |

A useful first study fixes the isotope, geometry and acquisition settings, runs one reference configuration, and checks its counts and gates before varying a detector parameter. Request the topic `studies` for parallel trials, reproducibility and reporting. Scientific inspiration is credited to Dominik Boras (2024), DOI 10.25972/OPUS-37663. Instrument data retain their own references.

