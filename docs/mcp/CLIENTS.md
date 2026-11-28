# Connect an AI agent to TwinPALS

A connection lets your assistant read the available detector components, propose a setup, submit local simulations and retrieve their spectra. TwinPALS performs the calculations on your Windows PC. You give the assistant the scientific question, the quantities it may vary and the evidence you want back. You can watch its submitted runs in the **Study observer**.

[Return to the TwinPALS guide](../../README.md#run-a-study-with-an-ai-agent) · [Study server, tools and recovery](README.md)

## Choose your client

| Where you use the assistant | Instructions |
| --- | --- |
| Codex desktop or CLI | [Codex](#codex) |
| Claude desktop application | [Claude Desktop](#claude-desktop) |
| Claude Code in a terminal | [Claude Code](#claude-code) |
| GitHub Copilot in a terminal | [GitHub Copilot CLI](#github-copilot-cli) |
| GitHub Copilot Chat in VS Code | [GitHub Copilot in VS Code](#github-copilot-in-vs-code) |

## Before connecting

1. Install TwinPALS or extract the complete Windows ZIP. Locate the folder containing **TwinPALS-MCP.exe**. The installer's default is `%LOCALAPPDATA%\Programs\TwinPALS 2.0`. With TwinPALS running, **Status and paths** in its tray menu also shows the location.
2. Open that folder in File Explorer, type `powershell` in the address bar and press Enter. Run the print command in the section for your client. It prints the actual executable path and arguments for this copy.
3. Keep existing servers when adding the generated entry. Installed copies use `%LOCALAPPDATA%\TwinPALS\Data` by default. Portable copies use the adjacent `data` folder. To choose a different workspace, add `--data-dir "D:\TwinPALS\Data"` before `--print-config`. The workspace determines which component catalogue and studies you see.

## Codex

Use Codex to run TwinPALS studies from a chat in the desktop app or terminal.

~~~powershell
.\TwinPALS-MCP.exe --print-config codex
~~~

Merge the printed TOML section into `%USERPROFILE%\.codex\config.toml` and reconnect. In the desktop app you can also open the MCP server settings and add a local **STDIO** server named `twinpals`. Enter the printed executable under **Command to launch**, then add each argument separately. For the example below the two arguments are `--data-dir` and `D:\TwinPALS\Data`. Type ordinary Windows paths in the form. TOML uses doubled backslashes in double-quoted strings.

~~~toml
[mcp_servers.twinpals]
command = "C:\\Tools\\TwinPALS\\TwinPALS-MCP.exe"
args = ["--data-dir", "D:\\TwinPALS\\Data"]
~~~

Save, enable the server and open a new chat. Check the workspace with the [first request](#check-the-connection). [Codex MCP documentation](https://developers.openai.com/codex/mcp/)

## Claude Desktop

Use the desktop application's **Settings → Developer → Edit Config** to open its local server configuration.

~~~powershell
.\TwinPALS-MCP.exe --print-config claude-desktop
~~~

Add the printed `twinpals` entry under `mcpServers` in `%APPDATA%\Claude\claude_desktop_config.json`. If this is a new file, the complete printed JSON is ready to use. Save, fully quit Claude Desktop, reopen it and send the [first request](#check-the-connection) in a chat. [Claude Desktop local server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)

## Claude Code

Use a project connection when you want TwinPALS tools in Claude Code sessions opened in a particular folder.

~~~powershell
.\TwinPALS-MCP.exe --print-config claude-code
~~~

In the folder where you run Claude Code, create or edit `.mcp.json`. Add the printed entry under `mcpServers`. Start a new Claude Code session there, approve the project server when prompted and use `/mcp` to check the connection. Then send the [first request](#check-the-connection). The generated paths refer to this PC. [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp)

## GitHub Copilot CLI

Use the CLI's per-user configuration when you want TwinPALS available from Copilot terminal sessions.

~~~powershell
.\TwinPALS-MCP.exe --print-config copilot-cli
~~~

Open `%USERPROFILE%\.copilot\mcp-config.json` or create it in the Copilot configuration folder. Merge the generated entry under `mcpServers`, including its `tools` field. Restart Copilot CLI, inspect the server with `/mcp` and send the [first request](#check-the-connection). [Copilot CLI MCP documentation](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers)

## GitHub Copilot in VS Code

Use a workspace connection when you want Copilot Chat to work with TwinPALS in a specific VS Code project.

~~~powershell
.\TwinPALS-MCP.exe --print-config vscode
~~~

Open the project in VS Code. Create or edit `.vscode/mcp.json` and merge the entry under `servers`. In the Command Palette, run **MCP: List Servers**, select **twinpals** and start it. Confirm trust if prompted. Open Copilot Chat in **Agent** mode, enable the TwinPALS tools in the tools picker and send the [first request](#check-the-connection). [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers)

## Check the connection

> Call the TwinPALS capabilities tool. Show me the application version and active data directory. Then list the scintillators available in that workspace.

The version and directory come from the local service. The component names come from that workspace's catalogue. If they look unfamiliar, compare the reported directory with **Status and paths** in the TwinPALS tray. If the portable folder moved, print the configuration again and update the client's executable and data paths.

To submit your first calculation, use the [START shielding study](../../README.md#example-study-shielding-the-start-detector). Open **Open study observer** from the tray to follow the queued and running steps.
