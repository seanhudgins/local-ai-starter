# services
Code for the long-running services, one subfolder each. Each script says which machine it's for.

| Folder | What | Machine |
|---|---|---|
| `ollama/` | First-load and check scripts. `firstload.ps1` (Docker container) for the PC; `firstload-mac.sh` + `firstload-mac.sb` (macOS sandbox), `check-mac.sh` for the Mac; `verify-model.sh` for both | PC + Mac |
| `open-webui/` | Browser chat, pinned and hash-locked | **[Your PC]** |
| `tailscale/` | Access policy; `check-edge.sh` runs from an edge device | Policy: admin console; check: Mac |

Coming: the `ask_local_model` MCP server (**v1-3**) and the LiteLLM gateway config and keyring launcher (**v1-4**), both **[Your PC]**.
Setup steps per OS: `docs/setup/PC.md`, `docs/setup/MAC.md`.
