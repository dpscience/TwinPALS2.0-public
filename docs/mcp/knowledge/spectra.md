# Direction, filtering and spectrum comparison

A → B selects A in its start PHS window and B in its stop window. B → A selects the reverse assignment. Stop–Stop selects two stop-window pulses. Merged uses the two start/stop directions. Channel letters on pulse-height panels and subtype labels always denote the physical detectors.

The analysis journal stores CF(B) − CF(A) in digitizer time. For display, subtract the recorded B − A cable delay when both delays are available. Reverse the sign for B → A, then subtract the display zero shift converted from ps to ns. The lifetime histogram includes its low limit and excludes its high limit. For A → B with a raw difference of 1.4 ns, a B − A cable delay of 0.3 ns and a zero shift of 100 ps, the displayed value is 1.0 ns.

Before filters already requires valid measured pulses and the relevant PHS assignment. After filters applies the enabled area and rise/fall selections. Stage totals describe different populations. Restricting the displayed lifetime time range removes out-of-range pairs from lifetime bins. The direction's PHS retains pulse heights for the full stage, including pairs whose time lies outside the lifetime plot.

The total trace is the complete stage histogram. The superimposed trace sums the enabled contribution selections with parent/subtype deduplication. Light and scatter selectors narrow class overlays. A time-range change, bin-width change or class overlay can be queried from a saved analysis. A change to waveform measurement or acceptance needs a new processing run. For reported percentages, record the stage, direction, denominator and displayed time range.

