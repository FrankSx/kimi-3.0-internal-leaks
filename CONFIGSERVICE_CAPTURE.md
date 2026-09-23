# ConfigService/GetConfig — Browser-Side Capture Analysis

**Source**: Firefox HAR, user-side capture 2026-09-23T16:22-04:00 (`recon_deep/configservice_getconfig_redacted.har.json`)
**Endpoint**: `POST https://www.kimi.ai/apiv2/kimi.gateway.config.v1.ConfigService/GetConfig` — Connect-RPC (`connect-protocol-version: 1`), request body `{"source":"CONFIG_SOURCE_SCRIPT"}`, 200, ~11.7 KB JSON config.

## 1. Identity linkage (the payoff)

The request's JWT and headers tie every plane of this repo to one account:

| Claim / header | Value | Matches |
|---|---|---|
| JWT `sub` | `d5qv71c268gnjn3dknig` | portal probe `creator_user_id` from unauthenticated `POST /api/v1/apps` |
| `x-traffic-id` header | `d5qv71c268gnjn3dknig` | same |
| JWT `abstract_user_id` | `d5qv71c268gnjn3dkhe0` | internal id, distinct from public sub |
| `device_id` / `x-msh-device-id` | `7674987196515888141` | device identity carried in JWT |
| JWT `region` | `overseas` | `REGION_OVERSEA` in syncToken |

One account identity spans: web session (JWT), portal app creation (creator_user_id),
and device. The sandbox's mounted `kimi_chat_id` (`1a0c7264-…`) is the Referer of
this very capture — the same conversation.

## 2. Token mechanics

- HS512 JWT, `iss=account`, `aud=[kimi.ai]`, `typ=access`, `app_id=kimi`
- **15-minute TTL** (iat 20:09:51Z → exp 20:24:51Z) — short-lived, good design;
  the durable secrets remain the `sk-kimi` sandbox key and refresh cookie.
- `membership.level=20`, `code_membership.level=20` — paid-tier claims embedded
  in the token (client-asserted, presumably gateway-verified).

## 3. What the config payload reveals

- **`ultraModeConfig` — the "workers" are config**: 20 named personas ("Yanis –
  Trend Forecaster", "Gannon – Progress Expediter", …) plus spinner action
  words ("Analyzing", "Searching", …) and idle messages ("Taking a coffee
  break", …). The multi-agent theater is a JSON config, not an orchestration
  layer.
- **`clawGroupChatConfig.kimiclawInstallCmd`**:
  `bash <(curl -fsSL https://cdn.kimi.com/kimi-claw/claw-install.sh) --bot-token __TOKEN__`
  — a curl-pipe-to-bash install recipe distributed in production config, with a
  bot token interpolated. A compromised CDN/config path = instant RCE for every
  user who copies it.
- `cdnDomains` includes `kimi-file.msdev.cc` — an internal dev domain exposed
  in production client config.
- WPS Office integration (`wpsAppId=AK20251216OINQCL`), slides "banana styles",
  Android KimiClaw APK link, project icon library, feedback taxonomy
  (fabrication/low-quality-reference complaint classes), and a `syncToken`
  (`script-59-2.3.0-en-US-REGION_OVERSEA-<hash>`) that fingerprints the
  deployed config version.

## 4. Redactions

Per `REDACTIONS.md`: JWT string, Cookie headers, and all structured cookie
values withheld (token was expired before publication; cookies are live session
material). Decoded claims — the provable factors — are preserved in the HAR's
`x-redaction-note` header.
