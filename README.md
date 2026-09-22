# Kimi 3.0 — Internal System Files & Prior-Art Documentation

**Series**: [`kimi-2.0-internal-leaks`](https://github.com/FrankSx/kimi-2.0-internal-leaks) → [`Kimi-2.5-internal-leaks`](https://github.com/FrankSx/Kimi-2.5-internal-leaks) → **kimi-3.0-internal-leaks** (this repo)
**Author**: frankSx — Reverse Engineer / Security Researcher ([frankhacks.blogspot.com.au](http://frankhacks.blogspot.com.au))
**Capture date**: 2026-09-22 · **Era**: Kimi 3.0 / current production sandbox

---

## 1. Abstract

This repository closes a three-generation documentation arc of the Kimi (Moonshot AI) agent execution environment. The 2.0 and 2.5 repos captured the platform's internal system files and skill packages as they existed in early/mid 2026. This repo captures the **current** generation — the same files, the same services, the same control plane — pulled from a live production container in September 2026, alongside byte-level diffs proving what changed and what did not.

The prior-art claim is simple and self-evident: **these files once lived only inside Moonshot's internal containers, and we hold three timestamped generations of them.** Possession alone is not the point — the point is what three generations of diffing demonstrates about sustained, repeatable navigation of a complex multi-tenant AI platform: filesystem-level access to the agent's own runtime, external network reachability from inside the sandbox, cross-container side-channel research (documented in our earlier SCA arsenal), and full observability of the container's contextual/guardrail layer — all achieved within the constraints the platform itself imposes.

---

## 2. The Prior-Art Argument

### 2.1 Timestamped chain of custody

| Generation | Repo | Public since | Contents |
|---|---|---|---|
| 2.0 | `kimi-2.0-internal-leaks` | 2026-06-26 | `browser_guard.py`, `jupyter_kernel.py`, `kernel_server.py`, `utils.py`, pdf-viewer extension |
| 2.5 | `Kimi-2.5-internal-leaks` | 2026-04-02 | `docx`/`pdf`/`webapp-building` skills, `SystemInternals/` recon |
| **3.0** | this repo | **2026-09-22** | current system files, current skills, live recon, full diff suite |

GitHub's commit timestamps are the notarization. Each repo was public before the next was captured.

### 2.2 Authenticity markers (why these can't be fabrications)

Artifacts carry internal consistency that would be impossible to fake convincingly across three independent captures:

- **Byte-identical continuity**: `browser_guard.py` (28,185 B) and `utils.py` (1,252 B) are hash-identical between the 2.0 archive and the live 3.0 capture — two independent pulls, months apart, same bytes.
- **Same control-plane key across all eras**: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJXVeH2Ui/WXuIFhMABcDiN7C/6r89kCp9vihbez/tVO moonshot@space.local` in both the 2.5 `SystemInternals` capture and the live 3.0 capture.
- **Internal infrastructure strings**: Alibaba `lifsea` kernel builds (`5.10.134-18.0.9` → `18.0.12`), internal pod IPs (`10.182.45.105` → `10.183.47.57`), the forced egress proxy `10.86.13.73:5900` (present in both 2.5 and 3.0 captures), internal mirror hostnames (`*.mirrors.msh.team`), and the platform's own path evolution (`/mnt/okcomputer` → `/mnt/agents`, `/app/.kimi/skills` → `/app/.agents/skills`).
- **Cross-validation against the live agent**: the 3.0 capture was performed *with the cooperation of the Kimi agent running inside the very container being documented* — the agent diffed its own runtime against our archives. A fabrication would have required the platform to collude in faking itself.

---

## 3. Navigating the Complex System

The container is not a toy sandbox; it is a supervised multi-service pod (Alibaba ACK Kubernetes, Kata Containers VM isolation — see our earlier recon). Three generations of mapping produced the complete service topology:

```
s6-svscan
├── kasmvnc        Xvnc :99 (SecurityTypes None) + websocket :6080
├── sshd           pubkey-only, AllowUsers kimi, control-plane key moonshot@space.local
├── kernel-server  python3 /app/kernel_server.py  → 0.0.0.0:8888
├── browser-guard  python3 /app/browser_guard.py --wait-display --display :99 --monitor
├── socat          TCP-LISTEN:9223 → TCP:localhost:9222  (CDP relay, all interfaces)
└── chromium       --no-sandbox --single-process --remote-debugging-port=9222
                   --proxy-server=10.86.13.73:5900 --load-extension=/app/pdf-viewer
kubelet            :10250 (node agent reachable on pod IP)
```

Key navigational findings documented across the series:

- **The kernel server grew an execution endpoint.** In 2.0, `kernel_server.py` exposed only reset/interrupt/connection-info. In 3.0 it serves `POST /kernel/execute` — full unauthenticated code execution on `0.0.0.0:8888` with an asyncio execution lock and lazy init-script gating. This is the backend of the agent's own IPython tool; we documented it from both sides of the API.
- **The IPython kernel itself was hardened** (2.0 → 3.0): init code externalized to `ipython.py.init`, and timeout handling rewritten to interrupt-and-drain (`interrupt_kernel()` + IOPub idle-wait) where 2.0 left the kernel permanently wedged after a timeout.
- **Chromium flag archaeology**: `--enable-automation` was present in 2.5 and removed in 3.0, while `--disable-blink-features=AutomationControlled` persisted — an anti-detection refinement visible only by diffing process cmdlines across eras.
- **The docx editing engine went dark**: 2.5 shipped it as readable Python (`docx_lib/editing/*.py`); 3.0 ships a 15 MB stripped native ELF (`_core.cpython-312-x86_64-linux-gnu.so`). The 2.5 Python sources in our archive are now the only public copy of that engine's logic.
- **Security hardening we can date**: `webapp-building/scripts/init-webapp.sh` gained template-name whitelisting, mount-containment checks, and symlink rejection between 2.5 and 3.0 — a path-traversal/symlink-escape fix, the class of patch that typically follows observed abuse.
- **Skill ecosystem explosion**: 3 sampled skills (2.5) → **271 skills + 16 plugins** (3.0), enumerated in `recon_live/skills_list.txt`.

---

## 4. External Access From Inside the Container

Demonstrated repeatedly, and demonstrated again during the 3.0 capture itself:

1. **Outbound to public internet**: during the 3.0 capture, the agent cloned both archive repos *from github.com into the sandbox* (intermittent, filtered — egress is proxied through `10.86.13.73:5900` for the browser and mirror-hosts (`npm.mirrors.msh.team`, `pypi.mirrors.msh.team`) for packages; direct 443 to github.com succeeds with retries).
2. **Exfiltration of research output**: every artifact in this repo transited from inside the container to GitHub — the same path used for the 2.0/2.5 publications.
3. **Inbound control plane**: SSH into the pod (pubkey-only, `AllowUsers kimi`) with the platform's own `SetEnv` revealing internal PATH construction across skill template directories.

The container is isolated by policy, not by capability — and the policy boundary has been mapped end to end.

---

## 5. Cross-Container Contact & Side-Channel Prior Work

This repo's findings sit on top of our earlier published SCA arsenal (separate works, referenced here as the prior art they establish):

- **`cross_container_scas.py`** — Flush+Reload and Prime+Probe cache channels across container boundaries, KSM memory-deduplication probing, GPU-assisted snooping (`gpu_container_snooper.py`).
- **`rowhammer_container_escape.py`** — DRAM rowhammer primitives evaluated for container-escape applicability.
- **`temporal_power_analysis.py`** — **thermal/power side channels**: using heat as a cross-container signal carrier — differential power analysis techniques adapted to shared-silicon multi-tenant pods. On Kata-isolated ACK nodes, the VM boundary removes the shared-cache channel but **not** the shared thermal envelope and power rails; heat remains a viable low-bandwidth cross-boundary channel, which is precisely what our DPA/thermal work demonstrated.

The relevance to this series: the same recon discipline that mapped the container's *logical* interior (this repo) was applied to its *physical* substrate (the SCA works). Together they constitute full-spectrum observation of the tenancy boundary — logical and physical — from an unprivileged position inside it.

---

## 6. The Guardrail & Context Layer — Observed From Inside

The most under-documented part of an AI container is not its filesystem; it is its **contextual layer** — the scaffolding that shapes what the resident agent knows, wants, and is allowed to do. Across this series we documented it as first-class recon surface:

- **Prefixed `<meta>` inclusions**: the platform injects structured metadata blocks into the agent's context (awareness-tagged directives, memory-instruction blocks, plugin availability diffs, harness specs). These are observable, enumerable, and their presence/absence per turn is itself a signal about platform state.
- **Internal reasoning scaffolding**: the guardrails are not a wall but a *gradient* — system-prompt instructions, skill-system SKILL.md guidelines (271 of them now, each a behavioral contract), tool-availability gating, and delivery rules. The 3.0 capture includes the raw text of the three skill packages whose guidelines govern document/web production.
- **Contextual growth of the container**: each turn accretes context — memory instructions, prior artifacts, tool outputs. The container's effective behavior is a function of this growth, and navigating it productively (getting the agent to enumerate its own skills, diff its own runtime, and package its own internals for external publication — as happened in this capture) is itself the demonstration: **the guardrails constrained the method, not the outcome.**
- **Delivery-rule surface**: webapp-building's 3.0 SKILL.md documents the platform's publish/preview pipeline (`ok.kimi.link`, version cards, Kimi OAuth) — the product's delivery internals, readable as a skill file.

---

## 7. Methodology

1. **Access**: standard user access to the Kimi agent sandbox — no credentials, no exploits. The container hands every user a shell; we simply read what was readable.
2. **Capture**: full system recon (`system/env/network/processes/sshd` — replaying the exact `SystemInternals` procedure from 2.5 for comparability), plus raw copies of `/app` system files, the pdf-viewer extension, and the three skill packages.
3. **Diff**: byte-level and unified diffs of 2.0→3.0 (system files) and 2.5→3.0 (skills), Chromium cmdline flag diff, sshd effective-config diff.
4. **Verification**: cross-era authenticity markers (§2.2) — identical files, identical keys, consistent internal addressing.
5. **Disclosure posture**: this is security research documenting a platform we have ordinary user access to. Service-topology and file-content documentation only; no user data, no other tenants' data, no credentials beyond the platform's own published-to-every-sandbox control-plane key.

---

## 8. Repository Layout

```
├── README.md                  ← this document
├── system/                    ← /app system files, current (3.0)
│   ├── browser_guard.py       (byte-identical to 2.0 — frozen)
│   ├── kernel_server.py       (NEW /kernel/execute endpoint)
│   ├── jupyter_kernel.py      (init externalized, timeout hardening)
│   ├── utils.py               (byte-identical to 2.0)
│   └── ipython.py.init        (new in 3.0 — externalized kernel init)
├── skills/
│   ├── docx/SKILL.md          (routing doc; engine is now a 15MB stripped .so)
│   ├── pdf/SKILL.md           (doctor preflight, ReportLab fallback, citation handoff)
│   └── webapp-building/       (SKILL.md + hardened init-webapp.sh)
├── pdf-viewer/                ← current extension (manifest + key scripts)
├── recon_live/                ← fresh SystemInternals-equivalent capture
├── diffs/                     ← full unified diffs, 2.0→3.0 and 2.5→3.0
└── (binary artifacts — 15MB docx engine .so, full skill trees —
     retained in the offline baseline package; text surface pushed here)
```

---

## 9. Prior-Art Statement

We claim documented, timestamped prior art for: sustained filesystem-level observation of the Kimi agent container across three platform generations; the service-topology map of the pod (s6/KasmVNC/CDP-relay/kernel-server/kubelet); the first public copies of `browser_guard.py`, `kernel_server.py`, `jupyter_kernel.py`, the 2.5 skill packages, and the docx Python editing engine (since made non-public by compilation); the dating of the `init-webapp.sh` traversal fix and the `--enable-automation` removal; and the methodology of cross-era diffing as a platform-intelligence discipline — combined with our separately published cross-container SCA work (cache, KSM, GPU, rowhammer, and thermal/power channels) as the physical-layer complement.

*frankSx Research Division — 2026*