# open-webui (v1-0, [Your PC]; Mac copy for the Mac's own models)

**On the Mac:** `bash services/open-webui/start-mac.sh`, with paths in `config-mac.json`. Same pinned version and settings, localhost only, never shared over Tailscale. See `docs/setup/MAC.md` §7. The rest of this page is Your PC.

Browser chat for the local Ollama models. Pinned to Open WebUI 0.13.0 with a hash-locked `uv.lock`.

| Setting | Value | Why |
|---|---|---|
| Bind | `127.0.0.1:8080` | Only Your PC can reach it until Tailscale is set up. `start.ps1` refuses any other host. |
| Data | `D:\ai\open-webui\data` | Chats, database and secret key stay out of the repo. |
| Program | `D:\ai\open-webui\venv` | The Python environment is several GB. |
| Models | Ollama at `127.0.0.1:11434` only | OpenAI-style providers are off until the v1-4 gateway. |
| Downloads | `OFFLINE_MODE`, `HF_HUB_OFFLINE` | No automatic model downloads. Document upload (RAG) needs an embedding model, so it won't work until we pick one. |

Paths and port live in `config.json`.

## Start
```powershell
pwsh -File services\open-webui\start.ps1
```
Open http://127.0.0.1:8080 and **create the admin account straight away**. The first account becomes admin and sign-up closes after it.

## Upgrade
1. Read the release notes.
2. Back up `D:\ai\open-webui\data`.
3. Change the version in `pyproject.toml`.
4. Run `uv lock --project services\open-webui`.
