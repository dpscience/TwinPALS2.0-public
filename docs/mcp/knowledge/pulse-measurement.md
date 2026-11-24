# Module 3 · Pulse measurement and filters

Module 3 measures the calibrated ADC waveform for each channel. It estimates the baseline and noise, accounts for signal polarity and optionally applies a median filter. The shared first/highest setting is applied separately to the samples in A and B. The first-pulse search uses a threshold crossing and a prominence criterion. Highest selects the greatest polarity-corrected sample. PHS uses the amplitude at the selected sample.

Readout-start baseline uses the median of the leading baseline samples. Pre-pulse mode starts with a short baseline estimate, locates the selected lobe and its leading edge, then takes a local median from the configured number of samples before onset, leaving the configured gap. A missing pre-pulse interval is reported as insufficient. Noise is estimated with 1.4826 times the median absolute deviation.

CF time is the rising crossing of the selected fraction of the pulse height. Rise time is the 10% to 90% interval. Linear crossings use adjacent calibrated samples. Nonlinear interpolation refines the crossings; intra-steps control that refinement. For fall time the trace must settle for three consecutive samples inside the baseline band, whose half-width is the larger of three noise scales and 0.5% of peak height. The last falling 10% crossing and preceding falling 90% crossing define the interval. An intervening dip followed by another rise can extend the measured fall. If the trace ends before it settles, fall time is unavailable.

Area is the sum of the absolute trapezoid contributions across the entire calibrated readout, in mV ns. For corrected samples y and calibrated times t, each contribution is |(y[i]+y[i+1]) × (t[i+1]−t[i]) / 2|. An additional pulse later in the window can therefore increase area while the selected peak still supplies PHS and CF.

PHS windows include the lower height and exclude the upper height. An enabled area filter compares the area residual relative to slope × height + intercept against the lower and upper widths. An enabled rise/fall filter requires both measured times inside its rotated ellipse. Example. For a 100 mV selected pulse and 25% CF, look for the rising 25 mV crossing in polarity-corrected coordinates.

