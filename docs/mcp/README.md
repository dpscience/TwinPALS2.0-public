# TwinPALS study server

TwinPALS-MCP.exe and the TwinPALS 2.0 study observer use the same 2.0.3 engines as the application. Extract the entire portable folder to a writable local drive. Keep both executables beside the shared _internal, .runtime, frontend, legal and seed directories.

## Connect a client

For a first connection, follow the [illustrated TwinPALS example](../../README.md#connect-twinpals-mcp-to-codex) or the [setup instructions for all five clients](CLIENTS.md). Each guide ends with a request that checks which local study workspace the agent can see.

With the Windows installer, open the installed program folder instead. The default is `%LOCALAPPDATA%\Programs\TwinPALS 2.0`. The generated configuration uses the installed workspace under `%LOCALAPPDATA%\TwinPALS\Data`; a portable copy uses its adjacent `data` directory. Stop the coordinator before updating. Reinstalling restores access to studies from the same workspace.

The server, coordinator and read-only observer are TwinPALS project code under the MIT license. Open **Third-party licenses** in the observer footer and choose **TwinPALS 2.0 MCP server and observer** to read the terms offline. The same catalog covers the Python runtime, the frontend and the scientific engines shipped with the desktop application. The server implements the [MCP stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) directly.

Open PowerShell in the release folder and print the configuration for your client. Each command prints the absolute executable and data paths for this copy.

    .\TwinPALS-MCP.exe --print-config codex
    .\TwinPALS-MCP.exe --print-config claude-desktop
    .\TwinPALS-MCP.exe --print-config claude-code
    .\TwinPALS-MCP.exe --print-config copilot-cli
    .\TwinPALS-MCP.exe --print-config vscode

For Codex, merge the TOML section into the client configuration. For Claude Desktop, merge the twinpals entry into mcpServers in claude_desktop_config.json. For Claude Code, the printed JSON also works as a project .mcp.json. Reload the client and call capabilities. Print the configuration again after relocating the portable folder. An optional --data-dir selects another writable workspace. Point it to the existing TwinPALS data directory to share its instrument and material catalogue.

For example, run `.\TwinPALS-MCP.exe --data-dir "D:\TwinPALS\Lab" --print-config codex` to generate a configuration for a separate workspace. A new directory starts with the factory catalogue and an empty study queue. Switching the configured path leaves existing studies and any active coordinator in their original workspace. Reconnect with the original path to see those studies again. The `capabilities` tool reports the active `data_directory`.

For GitHub Copilot CLI, merge the generated `copilot-cli` entry into the `mcpServers` object in `~/.copilot/mcp-config.json`. Open `/mcp` to inspect the connection. For GitHub Copilot in VS Code, merge the generated `vscode` entry into `servers` in the workspace's `.vscode/mcp.json`. Use **MCP: List Servers** to start TwinPALS and inspect its tools. In either client, ask for the TwinPALS `capabilities` tool to check the connection to the local study service.

The MCP transport is local stdio. The client launches its own adapter. The adapter starts or finds one coordinator for the selected data directory. Multiple clients can attach to the same studies. The coordinator and native workers run locally and continue after the client exits. The cloud client's planning, literature searches and writing require its own connection.

## Run a study

### Look up a method

Call `knowledge_read` with `{"topic":"overview"}` for the module map. Search with `knowledge_search`, for example `{"query":"pile-up"}`, then read the returned topic. Each chapter supplies the installed application version, content hash, implementation and verification references. Clients that present MCP resources can browse the same chapters at `twinpals://methods/overview` and the other listed URIs. Reading methods works locally, even before a study service starts.

Use the recorded profile and run receipt for experiment-specific claims. The source metadata reports the public repository and exact official release URL once available. Unpublished builds can have an empty release field. The tagged source links in each chapter refer to the implementation for that published version.

The Windows tray shows one **MCP connection** for each open client, including an idle client waiting on stdio. After the handshake, the row shows the name the client supplied. **Disconnect MCP client** closes that connection. The client can reconnect later.

The **MCP study service** appears when a tool needs the coordinator. Its **Observer** address gives the loopback IP and assigned HTTP port. **Open study observer** opens the authorized browser view. The center shows the selected step, its inputs and measured distributions. Choose **Study results** to compare steps and open saved reports. Closing the observer or disconnecting a client leaves studies running. **Stop MCP service** requests confirmation while steps are active or queued. Unfinished attempts replay from their saved inputs on restart.

During interactive Windows uninstallation, **Close processes and continue** disconnects clients and stops services belonging to the installation being removed. Silent uninstallation requires these processes to have exited first. Data retention is a separate choice.

1. Use profile_get to inspect each module's saved settings and validation schema. Use catalogue_list and catalogue_get for physical properties, curves, units and references. stream_list and stream_inspect discover existing input files.
2. Submit a study using study_submit. Supply a stable request_id and a name. Each step has a key, module, optional complete profile and individual JSON Pointer changes. The source may be Na-22 or Co-60. A later step can reuse an earlier step's output through input_from. Multiple variants can share the same M1 or M2 input files.
3. Read study_status and run_result. Query a saved lifetime journal with spectrum_query to change binning, time limits, direction and class overlays. Inspect individual ADC traces in a completed M2 or M3 run with waveform_read. A new measurement filter or detector setup belongs in a new processing variant. Include a queries array in a step to save supported workbench queries at completion. Use workbench_routes and workbench_call for geometry validation, PMT response, pulse transport or material exchange.
4. Compare run-level numeric metrics with study_compare. Generate an evidence-linked Markdown report with study_report. Save an agent-authored paper, table or methods section with study_document and cite the underlying run IDs. Validate a proposed optimum on independent seeds and report the uncertainty relevant to the objective. A simulated result is evidence about the selected model.
5. Supply an existing pulse stream as inputs on an M3 step to remeasure it. M1 and M2 support operation "import" to analyze pre-existing transport or pulse streams. Paths are either absolute or relative to the data directory. Live calls use the run ID. Completed steps retain their analysis, saved queries, streams and receipt. Large tool results return a local path and a response ID for paginated result_read calls.

For example, send the following as study_submit arguments. The two transport variants can execute concurrently. The remaining steps consume the outputs of the reference setup.

    {
      "request_id": "detector-comparison-01",
      "name": "Detector comparison",
      "objective": "Compare detector yield at a fixed event count",
      "max_parallel": 2,
      "cpu_budget": 4,
      "steps": [
        {"key": "reference", "module": 1,
         "changes": {"/run/events": 1000, "/run/secondary_events": 1000,
                     "/run/auto_seed": false, "/run/seed": 73125}},
        {"key": "separation", "module": 1,
         "changes": {"/run/events": 1000, "/run/secondary_events": 1000,
                     "/run/auto_seed": false, "/run/seed": 73125,
                     "/detectors/0/distance_mm": 5}},
        {"key": "digitize", "module": 2, "input_from": "reference",
         "changes": {"/waveform_pairs": 8, "/activity_Bq": 10000,
                     "/acquisition/trigger": "either", "/channels/0/threshold_mV": 1,
                     "/channels/1/threshold_mV": 1}},
        {"key": "lifetime", "module": 3, "input_from": "digitize"}
      ]
    }

## Observe

Call observer_open or run TwinPALS-MCP.exe --observer. The observer displays studies, live progress, the recorded setup, detector geometry, energy or pulse-height histograms and lifetime spectra. Select a run to pin it, inspect its settings or follow the active run. Navigation, camera controls and plot zoom affect only the observer. Keep the supplied link private. It grants read access to the local observer. The desktop editor uses its usual client connection.

## Persistence and recovery

The queue is stored in data/studies/queue.sqlite. Each study directory holds manifest.json and a transactionally consistent catalogue.tpdb snapshot. Each step has a permanent run ID. Every attempt writes into a separate directory. Successful completion commits a receipt with settings, actual seed, worker count, input and output identities, measured metrics and artifact paths. Stream identities contain length, modification time and a SHA-256 digest of the first and last 64 KiB. The catalogue digest covers the entire file. Leave input streams intact until dependent steps finish.

Repeated submission of an identical request_id and definition returns the same study and run IDs. Reusing the key with changed parameters returns an error. Explicit seeds support comparisons across separately submitted variants. Automatic seeds are generated once when the study is accepted. The CPU budget bounds assigned simulation workers across concurrently scheduled steps in a coordinator. Independent studies sharing that coordinator also share the workstation limit.

A disconnected client or Internet outage leaves submitted steps running. While work is pending, the portable service registers a per-user Windows sign-in command for this workspace. After a power interruption Windows must boot and the user must sign in. The service keeps committed steps and replays an interrupted step from its beginning using its recorded inputs, parameters and seed. Partial attempts stay in their own directories. Windows sign-in recovery requires access to the original executable, data folder and streams. The registration is removed when the queue reaches terminal states. A workstation policy that blocks registration is reported by capabilities.

To resume manually, run TwinPALS-MCP.exe --resume. To stop this workspace's coordinator while preserving pending work, use --shutdown. For a disposable workspace, pass --no-logon-resume from the first launch. run_cancel explicitly cancels one job. run_retry reuses its original settings in a fresh attempt. A blocked dependent can be retried after its parent succeeds.

## Client documentation

- [GitHub Copilot CLI local MCP configuration](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers)
- [MCP servers in VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers)

- [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Claude Desktop local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp)

TwinPALS 2.0 · © 2026 Danny Petschke · twinpals@proton.me. Scientific basis · Dominik Boras (2024), Universität Würzburg. [Dissertation](https://doi.org/10.25972/OPUS-37663)

