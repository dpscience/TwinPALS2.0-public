# Reproducible studies and reports

Start with a measurable objective, constraints, isotope and acquisition gate. Record the baseline profile, units, event count and each changed parameter. Distinguish physical time from processing duration. A claim about a simulated configuration is conditional on the simulation, input catalogue and settings.

Use study_submit with a stable request_id. Repeating the identical request reuses the study. Reusing the ID with a different specification is rejected. Independent steps can run concurrently within the study's max_parallel and cpu_budget and the coordinator's total CPU budget. An input_from dependency waits for its upstream result. Reuse transport inputs for a digitizer comparison and waveform inputs for an analysis-only comparison when applicable.

The agent uses local stdio. The Windows tray displays the observer's loopback IP and assigned HTTP port. Use Open study observer in the tray or observer_open through MCP to obtain authorized access to the browser view.

Closing the client or read-only observer leaves the coordinator running. On service recovery, unfinished steps replay from saved inputs and seeds in a new attempt. Receipt-committed results can be reused. Cancellation is recorded; dependent steps can be blocked. Use study_status to distinguish completed, partial, failed, blocked, cancelled and pending work.

For optimization, compare the reference and candidate on a common workload, then repeat promising configurations on independent seeds. Report both resolution and efficiency with their denominators. Include statistical uncertainty, trials and any filter/window selection. If the aim is instrument performance, document what has been experimentally validated.

For a manuscript, retrieve run_result for each cited run. Record the run and attempt, status, profile hash, inputs, isotope, timing convention, units and analysis configuration. Save result tables and a methods section via the study tools. Cite the versioned software release when present, the scientific basis, and the actual component sources. The methods handbook describes the program. The run receipt supports a numerical result.

