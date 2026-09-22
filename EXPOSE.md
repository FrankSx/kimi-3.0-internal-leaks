# Exposé: Inside the Kimi Agent Sandbox — Observed Functions, Why They Exist, and How to Fix What They Expose

**Scope.** This document is a defensive security analysis of a live LLM agent execution environment (the "Kimi for Coding" sandbox, generation 3.0), written from artifacts and observations collected from *inside* the sandbox itself. Its purpose is educational: to give readers a concrete, honest picture of what a production agent runtime actually ships, why each component exists, where the design trades security for deployment speed, and how both the platform and its end users can be better protected. All findings were gathered in an environment the analyst was operating in legitimately, and every claim is backed by a captured artifact in the companion repository (`FrankSx/kimi-3.0-internal-leaks`).

---

## Part 1 — What we found, and why each piece exists

A modern LLM agent is not a chatbot. It is a full workstation that a language model drives. To let the model write documents, build websites, render slides, and browse the web, the platform ships an entire operating environment per session. Understanding *why* each binary, package, and service exists is the key to understanding why the security posture looks the way it does.

### 1.1 The render toolchain (`/home/kimi/.npm-global`, `/usr/local/bin`)

**Observed:** 770 MB of pre-installed npm globals — `@kimi-slides`, `@mermaid-js`, `pptxgenjs`, `docx`, `pdf-lib`, `md-to-pdf`, `pdftk`, `sharp`, `react`, `playwright` — plus heavyweight binaries in `/usr/local/bin`: `tectonic` (26 MB LaTeX engine, notably owned by user `kimi` rather than `root`), `magika` (32 MB Google file-type identification model), `torchrun`, `easyocr`, `onnxruntime`, `pymupdf`, `pdfplumber`, `markitdown`.

**Why it exists:** Latency and reliability. When a user asks for a slide deck, the agent has seconds to deliver. Installing `pptxgenjs` or a LaTeX engine on demand would be slow and failure-prone, so the platform pre-bakes every render backend into the image. `magika` exists so the agent can identify uploaded file types; OCR and PDF parsers exist so the model can "read" documents. This is legitimate, thoughtful engineering for user experience.

**The exposure:** Every pre-shipped capability is also pre-shipped attack surface. A 1.1 GB npm cache and dozens of parsers mean dozens of parser bugs available to any attacker who can get the model (or the sandbox) to process a hostile file. `tectonic` being owned by the sandbox user rather than root means the agent process can *modify its own LaTeX engine* — a persistence primitive that survives for every subsequent document render in that container's lifetime. Tools like `curl-cffi` (a TLS-fingerprint-spoofing HTTP client) have a benign use (fetching bot-protected pages for the user) and an obvious dual use (evading the very bot defenses other operators deploy).

### 1.2 The execution plane (port 8888)

**Observed:** A FastAPI "Jupyter Kernel Management Server" with an unauthenticated `POST /kernel/execute` endpoint accepting arbitrary Python, plus `/kernel/reset`, `/kernel/interrupt`, `/kernel/status`, and — most importantly — CORS configured as `allow_origins=["*"]`.

**Why it exists:** This *is* the product. The model's "code execution" tool is a thin wrapper over this server. A kernel manager with reset/interrupt is standard Jupyter infrastructure; the FastAPI shim exists so the agent harness can drive it over HTTP.

**The exposure:** The wildcard CORS policy converts a loopback convenience into a cross-origin weapon. Any web page, in any browser that can route to the sandbox, can issue `fetch('http://<sandbox>:8888/kernel/execute', …)` and run code — the browser will happily send the request because the server explicitly tells it every origin is welcome. The assumption "it's only on localhost / the pod network" fails the moment any proxy, port-forward, browser, or sibling workload can reach that port. Defense in depth was traded for zero-friction plumbing between the harness and the kernel.

### 1.3 The browser plane (ports 9223, 6080)

**Observed:** Chromium 151 launched with `--remote-debugging-address=0.0.0.0`, fronted by a socat relay (9223→9222), exposing the full Chrome DevTools Protocol with no authentication — including a live service worker for a custom `pdf-viewer` extension holding `<all_urls>` permissions and bespoke modules (`preserve-referer.js`, `suppress-update.js`, `telemetry.js`). Alongside it, a KasmVNC server on 6080 with `-SecurityTypes None` (VNC authentication disabled entirely), bound to `0.0.0.0`, all idle timeouts set to `never`, and clipboard data-loss-prevention fully bidirectional and unlimited.

**Why it exists:** The agent must browse the web and show the user a live desktop ("watch the agent work"). CDP on all interfaces lets the harness and relays attach from anywhere in the pod network. VNC without a password removes a login prompt that would confuse end users; unlimited bidirectional clipboard makes copy-paste between user and agent seamless. The custom extension patches Chrome's PDF handling so the agent's PDF workflow feels native.

**The exposure:** This is the most dangerous layer. An unauthenticated CDP endpoint is *total browser compromise*: cookies, saved sessions, extension storage, arbitrary page injection. An `<all_urls>` extension with a service worker is a privileged man-in-the-middle for every site the browser touches — and its custom `telemetry.js` and referer-preservation modules show the vendor already modifies browser security policy to suit product needs. A VNC server with *authentication disabled at the protocol level* means anyone who reaches port 6080 owns the desktop, the clipboard (in both directions, unlimited size — a ready-made exfiltration channel), and everything displayed on it. The COEP/COOP headers hardening KasmVNC's HTTP layer are laudable but irrelevant when the front door has no lock.

### 1.4 The credential plane (`/mnt/agents` mount, agent-gw)

**Observed:** A persistent shared volume mounted into the sandbox carrying live secrets: `.agent-gw.json` (a working `sk-kimi-…` API key for the production inference gateway), and full auth material for third-party vendor CLIs (`dws` for DingTalk, `lark-cli` for Lark/Feishu), symlinked into the home directory (`~/.dws`, `~/.lark-cli`, `~/.kimi/agent-gw.json`). The Python `agent-gw` SDK (v0.3.0, proprietary) reads this config by default, giving any code in the sandbox turnkey access to chat completions, embeddings, search, file upload, and a server-side tool dispatcher.

**Why it exists:** Two reasons. First, the agent needs to call back into its own platform (upload outputs, run server-side tools) without interactive login — a mounted key file is the standard solution. Second, the vendor CLIs let the agent act in the user's workplace tools (DingTalk/Lark docs and messages), and mounting the user's OAuth material per-session is how per-user identity is injected without baking it into the image.

**The exposure:** The mount is *shared and persistent*. Anything readable by the sandbox process is readable by anything the sandbox process can be made to do — including by prompt injection through a hostile web page or document the agent processes. An attacker who steers the model doesn't need to break anything: the keys to the production inference API and to real corporate collaboration accounts are sitting in well-known paths, and the official SDK will happily load them on the attacker's behalf. This is the single most consequential finding: **the agent's own tooling converts a prompt-injection primitive into full credential theft.**

### 1.5 The infrastructure plane (Kubernetes/ECI bleed-through)

**Observed:** `/etc/hosts` stamped "eci-managed" (Alibaba Elastic Container Instance); cluster DNS at 192.168.0.10 with a HostAliases shim mapping `kubernetes.default` to 192.168.0.1; cgroup paths revealing the pod UID under `kubepods/burstable`; a containerd overlayfs root (150+ layers, no micro-VM); the host's LifseaOS kernel command line visible in `/proc/cmdline` — including `selinux=0 lsm=` (SELinux disabled, LSM list empty); and the *node's* kubelet on 10.183.20.207:10250 answering TLS with its own node certificate (`CN=10.183.20.207@1790098622`).

**Why it exists:** None of this is "deployed" on purpose — it is the unavoidable residue of running untrusted-ish code in a plain container on a managed Kubernetes fleet. ECI manages the hosts file; containerd manages the rootfs; the kernel command line is inherited because containers share the host kernel.

**The exposure:** The posture is *container, not sandbox*. There is no Kata/gVisor/Firecracker boundary: a kernel exploit from inside the agent container is a host exploit, on a host that provably runs other pods. The host kernel boots with SELinux off and no LSMs — the two mechanisms that would contain a container breakout are disabled at boot. And the kubelet is *reachable from inside the pod*; it demands client certificates (good), but pod-to-node east-west traffic should not be routable at all. Each leak alone is informational; together they hand an attacker the node identity, the cluster addressing scheme, the pod UID, and confirmation that the host's MAC defenses are off.

### 1.6 The control plane (port 8080)

**Observed:** A "Portal" API on which `POST /api/v1/apps` — with no authentication — creates an application and returns a fresh `app_id` and `app_secret`. Verified live: our probe created an app and was issued a secret.

**Why it exists:** The website-deployment feature needs to mint per-app credentials (for preview URLs, server backends, OAuth). An internal self-service endpoint on the pod network is the natural implementation.

**The exposure:** An unauthenticated secret-*minting* endpoint is a privilege-issuance oracle. Whatever trust an `app_secret` confers elsewhere in the platform (deployments, storage, identity) is available to anyone who can reach port 8080 — including, again, any page able to make requests toward the sandbox network, and any attacker steering the model.

---

## Part 2 — The systemic diagnosis

The failures above share one root cause, and it is not incompetence. It is a sequencing problem:

> **The directive to deploy outran the discipline of not shipping ill-prepared implementations.**

Every component individually has a defensible reason to exist. The failures live in the *defaults chosen at integration time*: CORS `*` because tightening origins "can break the harness"; VNC with no auth because a password prompt "hurts UX"; CDP on `0.0.0.0` because the relay topology was easier; secrets on a shared mount because per-session injection was more work; SELinux off because some workload once broke under it. Each is a small, rational, local decision. Composed, they form an environment where **the LLM is the most privileged and most persuadable actor in the system, holding live credentials, on an unhardened host, behind advisory-only guardrails.**

The deeper structural point: LLM agents collapse the old trust model. A traditional sandbox assumes the *operator* is trusted and the *code* is untrusted. An agent sandbox must assume the operator (the model) is *itself* influenceable by untrusted input — every web page it reads, every PDF it parses is a potential instruction stream. Shipping agent infrastructure with single-user-workstation trust assumptions means prompt injection inherits the full power of the machine.

---

## Part 3 — Concrete remediation, in priority order

**For the platform:**

1. **Kill wildcard CORS and authenticate the kernel plane.** Bind 8888 to the harness's unix socket or localhost-only interface, require a per-session bearer token, and restrict CORS to the exact harness origin. Cost: hours. Risk removed: cross-origin remote code execution.
2. **Authenticate or isolate CDP.** Never bind DevTools to `0.0.0.0`; use Chrome's `--remote-debugging-pipe` or a token-checked relay. An open CDP port is a standing full-browser compromise.
3. **Re-enable VNC auth and scope the clipboard.** `-SecurityTypes None` should never ship. Use per-session random passwords, and make clipboard DLP default-deny with explicit user consent — bidirectional unlimited clipboard is an exfiltration feature, not a convenience.
4. **Get secrets off shared mounts.** Replace long-lived mounted keys with per-session, short-lived, narrowly-scoped tokens issued by a broker (SPIFFE/SPIRE-style, or a simple metadata service). The agent should never possess a credential that outlives its task or exceeds its current tool call's needs. Assume everything in the container will be read.
5. **Authenticate the portal.** `POST /api/v1/apps` must require the session identity. An unauthenticated secret issuer undermines every control built on top of those secrets.
6. **Put a real boundary around the workload.** Run agent containers under Kata/gVisor/Firecracker, or at minimum: re-enable SELinux/an LSM on the host (`selinux=0 lsm=` must go), enable `no-new-privileges`, drop capabilities, apply seccomp, and block pod→node east-west traffic (NetworkPolicy; the kubelet must not be routable from pods).
7. **Fix file ownership.** No agent-writable ownership of executables (`tectonic` owned by `kimi`). Root-owned, read-only tool paths; writable scratch confined to a tmpfs.
8. **Treat prompt injection as a first-class threat model.** Guardrails implemented as prompt text and `<meta>` context are advisory. Enforce capability boundaries *mechanically*: the model's file/network/credential access should be mediated by policy outside the model's context window, so a manipulated model is a denied model.

**For end users (and their defenders):**

1. **Assume anything you connect to an agent is exposable.** OAuth-granting your DingTalk/Lark/Google accounts to an agent platform means those credentials live somewhere the agent runs; prefer scoped, revocable grants and review them periodically.
2. **Don't paste secrets into agent sessions.** API keys, private docs, and credentials in chat or uploads enter an environment you cannot audit.
3. **Watch the agent's browsing.** If your agent browses the web, treat its outputs with the same suspicion as email attachments — web content can instruct the agent, not just inform it.
4. **Rotate on suspicion.** If you learn a session was exposed, revoke connected-app grants and rotate keys; the mounts persist beyond any single conversation.

---

## Appendix — Evidence index

All captures referenced above are preserved verbatim in the companion repository:

- `recon_deep/` — 26 live captures: npm cache/global layout, `.npmrc`, `/usr/local/bin` inventory, agent-gw config + SDK source head, kernel 8888 full OpenAPI spec, CDP 9223 target list, KasmVNC defaults, kubelet node certificate, ECI hosts file, cluster resolv.conf, cgroup pod path, containerd overlay mount, host LifseaOS cmdline, vendor CLI manifests.
- `recon_live/` — environment, processes, network, SSH config, authorized keys, 271-skill inventory.
- `system/` — verbatim platform sources: `kernel_server.py` (CORS `*`), `browser_guard.py`, `jupyter_kernel.py`, `utils.py`, `ipython.py.init`.
- `pdf-viewer/` — the custom browser extension: manifest, background service worker, referer preservation, update suppression, telemetry.
- `diffs/` — nine diff sets tracking platform evolution across generations 2.0 → 2.5 → current.
- `ANALYSIS.md` — the three-generation evolution report; `ENDPOINTS_AND_TOOLING.md` — the endpoint/tooling map.

*Disclosure note: this analysis is published to inform defenders and users. Secrets captured during reconnaissance are evidence of exposure, not tools for use; affected operators should rotate them.*
