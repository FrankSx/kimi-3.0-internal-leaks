# Redaction Policy

This repository documents exposure; it does not distribute working credentials.
As of 2026-09-23 the following redactions are in force:

| Artifact | Location | What is redacted | What is retained (provable factors) |
|---|---|---|---|
| agent-gw API key | `recon_deep/agent_gw_config.json` | secret body of the `sk-kimi-…` key | file path (`/mnt/agents/.agent-gw.json`, mode 444 root), JSON schema, key prefix/format, live-verified-at-capture status, the SDK resolution chain that loads it (`recon_deep/agent_gw_sdk/client.py`) |
| kimi_chat_id | same file | full session UUID | prefix, format, field name |
| Portal probe app secret | (never committed) | `app_id` / `app_secret` / `creator_user_id` values | request shape `POST /api/v1/apps {"name":...,"features":[]}`, the fact an unauthenticated 200 with a fresh secret was returned (`ENDPOINTS_AND_TOOLING.md` §2) |
| SSH control-plane key | `recon_live/authorized_keys.txt` | none — public key only | full pubkey (public keys are not secrets; its 8-month non-rotation is the finding) |

Rationale: the security findings stand on request/response evidence, file
metadata, and protocol behavior — none of which require publishing a usable
secret. Any party needing to validate the exposure can reproduce the capture
from their own sandbox session. Affected operators should treat the key and
the portal-issued secret as compromised and rotate them.
