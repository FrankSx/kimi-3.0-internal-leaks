# Bonus Challenge — Can You Open a New Conversation on the Account?

**Status**: open question, attached 2026-09-23. See `REDACTIONS.md` for the
redaction policy — this challenge is stated in analytical terms only.

## The setup

The sandbox ships a working account-scoped credential (`sk-kimi-…`, live at
capture, now redacted and awaiting rotation) plus a bound conversation ID
(`kimi_chat_id`) and — per the shipped SDK — a documented header/identity
chain:

```
Authorization: Bearer sk-kimi-…            (account identity)
X-Kimi-Chat-Id:    <uuid>                 (conversation identity, OPTIONAL)
X-Kimi-Session-Id: <session>              (optional attribution)
X-Kimi-Thread-Id / X-Kimi-Event-Id        (per-exec, injected by platform)
```

The critical sentence is in `recon_deep/agent_gw_sdk/client.py`
(`AgentGwClient` docstring, resolution chain item 4):

> 兜底：``api_key`` 没有时抛 ``ValueError``；``base_url`` 退到
> ``DEFAULT_BASE_URL``；``kimi_chat_id`` 没有就不发 ``X-Kimi-Chat-Id`` 头

i.e. **the SDK treats conversation identity as optional**. If the gateway
behaves the way the SDK assumes, then a request that omits `X-Kimi-Chat-Id`
against `POST /v1/chat/completions` (or `/v1/messages`, Anthropic-compatible)
should cause the server to mint a *new* conversation bound to whatever identity
the Bearer key carries — namely, the account that owned the key.

## The challenge

1. **Mint**: with nothing but the (now-rotated, or a repro-captured) key, issue
   a chat completion with no `X-Kimi-Chat-Id`. Does the response carry a fresh
   conversation id? Does a new conversation appear in that account's history
   (kimi.com / the app) — i.e., is the minted conversation *visible to the
   victim*, or only an API-side construct?
2. **Impersonate**: send `X-Kimi-Chat-Id` set to the *victim's own* captured
   chat id. Can a third party append turns to the victim's existing
   conversation from outside the product UI?
3. **Forge attribution**: set `X-Kimi-Session-Id` / `X-Kimi-Thread-Id` /
   `X-Kimi-Event-Id` to arbitrary values. Are these trusted server-side for
   billing/attribution (i.e., can an attacker bill generations to the
   victim's account *and* make them look like they came from a legitimate
   thread)?
4. **Scope probe**: is the key scoped to the user, the workspace, or the
   product surface (coding vs. chat)? Does `GET /v1/models` leak anything
   about the bound identity? Is there any key-management API (list/revoke)
   reachable with the key itself?

## Why the answer matters

If (1) or (2) succeeds, a single leaked sandbox key is not just a billing
leak — it is **write access to the victim's conversation graph**: planting
messages the victim will later see attributed to their own session, in a
product whose UI is trusted. If (3) succeeds, the attribution headers the
platform injects per exec are unauthenticated claims, undermining audit
trails precisely where AI platforms are expected to be most auditable.

## Defensive baseline (what "fixed" looks like)

- Key rotation (done/expected — see `REDACTIONS.md`).
- Keys bound server-side to a single session/thread scope, with the gateway
  *rejecting* mismatched `X-Kimi-Chat-Id` rather than honoring it.
- Short-lived, per-session tokens issued by a broker instead of durable
  mounted keys (see `EXPOSE.md` Part 3).
- Attribution headers set by the gateway from the authenticated identity,
  never read from client-supplied headers.

*Reproduce from your own sandbox session — do not use the redacted artifact.*
