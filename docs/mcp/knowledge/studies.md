# Reproducible studies and reports

Start with a measurable objective, constraints, isotope and acquisition gate. Record the baseline profile, units, event count and each changed parameter. Distinguish physical time from processing duration. A claim about a simulated configuration is conditional on the simulation, input catalogue and settings.

Use study_submit with a stable request_id. Repeating the identical request reuses the study. Reusing the ID with a different specification is rejected. Independent steps can run concurrently within the study's max_parallel and cpu_budget and the coordinator's total CPU budget. An input_from dependency waits for its upstream result. Reuse transport inputs for a digitizer comparison and waveform inputs for an analysis-only comparison when applicable.

The agent uses local stdio. On Windows, each open adapter has an MCP connection row in the shared tray. It can stay connected after the study service stops. Disconnect MCP client closes the selected adapter. When the coordinator is running, its separate row shows the observer's loopback IP and assigned HTTP port. Use Open study observer in the tray or observer_open through MCP to obtain authorized access to the browser view.

Closing the client or read-only observer leaves the coordinator running. On service recovery, unfinished steps replay from saved inputs and seeds in a new attempt. Receipt-committed results can be reused. Cancellation is recorded; dependent steps can be blocked. Use study_status to distinguish completed, partial, failed, blocked, cancelled and pending work.

For optimization, compare the reference and candidate on a common workload, then repeat promising configurations on independent seeds. Report both resolution and efficiency with their denominators. Include statistical uncertainty, trials and any filter/window selection. If the aim is instrument performance, document what has been experimentally validated.

For a manuscript, retrieve run_result for each cited run. Record the run and attempt, status, profile hash, inputs, isotope, timing convention, units and analysis configuration. Save result tables and a methods section via the study tools. Cite the versioned software release when present, the scientific basis, and the actual component sources. The methods handbook describes the program. The run receipt supports a numerical result.


## Reading the observer

The selected step shows the submitted objective, its position in the study and its input step or stream. Follow keeps the same active run on screen during parallel work. Select another step to pin it. A study-specific observer link stays within that study.

For Module 1, compare crystal interactions, events with a signal on either anode and events with signals on both anodes against the event count for each primary. New attempts show the deposited-energy distribution for positive deposits. A sampled trajectory illustrates one event. Module 2 offers pulse height, area and the B minus A peak-time difference. Module 3 shows the accepted fraction of all pairs read. Choose a direction to see the lifetime distribution and its own in-range and outside-range counts. Before and after filters are shown together when area or shape cuts are active. Compact lifetime previews retain bin edges and state the displayed bin width.

When a step has saved named queries, Measurement opens its first saved query. Choose Module overview to inspect the standard distributions. The original query JSON is available even when its result has no chart representation. Study results compares inputs, differing run settings and committed counts among steps of the same module and operation. For lifetime steps, select a second run and a common result to overlay their counts. The plot requires a matching direction, time grid and selection. Choose the filter stage when both runs provide it. Open a saved report or study document there for conclusions such as an IRF fit. A partial import describes only its readable records. A pending or unsuccessful attempt has no committed result.
