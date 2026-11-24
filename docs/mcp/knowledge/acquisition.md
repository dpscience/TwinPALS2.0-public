# Module 2 · Acquisition and measurement time

Module 2 places recorded analog responses on a simulated source clock using the configured activity and source model. Na-22 combines prompt and annihilation roles with the selected lifetime distribution. Co-60 preserves the matched cascade. The saved Module 1 response already includes the PMT transit-time spread. Module 2 applies its channel attenuation, cable delay and digitizer settings.

Channels have their own polarity and trigger thresholds. For a coincidence trigger, both crossings must satisfy the configured coincidence gate. The acquisition delay positions the readout window around the trigger. Nonparalyzable dead time limits subsequent accepted records while source time continues. Summed subthreshold contributions can trigger together.

The output stores calibrated time coordinates and sampled voltages for A and B, the trigger and readout times, and references to the contributing transport records. Referenced photoelectron arrays and ancestry are embedded. Inspect the exact digitizer mode, ADC rails and sample count in the recorded header.

Module 3 measurement time comes from the Module 2 simulated source-clock timestamp at the start of the most recently processed readout. Its elapsed and remaining processing times use the computer clock. Module 2 monitoring can extend through the final digitizer dead time.

Example. If the last processed readout starts at 3,000,000,000 ns on the source clock, the displayed physical measurement time is 3 s, regardless of how long the computer spent reading the file.

