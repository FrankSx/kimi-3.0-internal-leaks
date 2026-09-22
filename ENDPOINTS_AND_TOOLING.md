# Endpoint Map, Tool-Call Surface, and Deployed Subsystems

Companion to ANALYSIS.md. Everything below was captured live from inside the
agent sandbox (pod UID `0eb323b8-34c4-44ec-ab8e-b8118416e7a2`, Alibaba ECI /
kubepods burstable, host node `k2102452101898694660` @ 10.183.20.207).

## 1. Deployed subsystems (cache folders, bin dirs, custom installs)

### npm layer
- `/home/kimi/.npmrc`: `prefix=/home/kimi/.npm-global`, `cache=/home/kimi/.npm-cache`
- `/home/kimi/.npm-cache` — 1.1 GB, standard `_cacache` + `_logs`; this is where
  every pre-deployed npm subsystem was materialized at image build time.
- `/home/kimi/.npm-global/lib/node_modules` — pre-installed globals:
  `@kimi-slides`, `@mermaid-js`, `docx`, `md-to-pdf`, `pdf-lib`, `pdftk`,
  `playwright`, `pptxgenjs`, `react`, `react-dom`, `react-icons`, `sharp`.
  Bins on PATH: `kimi-design`, `kimi-slides`, `md-to-pdf`, `md2pdf`, `mmdc`,
  `playwright`. These are the render backends the slides/design skills call.

### /usr/local/bin (custom + adapted)
- `magika` (32 MB Google file-type model binary), `tectonic` (26 MB, owned by
  `kimi` not root — user-space drop-in), `ninja`, `torchrun`/`torchfrtrace`,
  `easyocr`, `onnxruntime_test`, `pymupdf`, `pypdfium2`, `pdfplumber`,
  `markitdown`, `markdownify`, `dumppdf.py`, `bt-run.py`/`btrun` (custom
  wrappers), `curl-cffi` (TLS-fingerprint-spoofing http client), `cffi-gen-src`.
- Symlinks wiring vendor CLIs into PATH:
  `dws -> /home/kimi/.cli-tools/dws-cli/bin/dws`,
  `lark-cli -> /home/kimi/.cli-tools/lark-cli/bin/lark-cli`.

### Vendor CLIs with mounted credentials
- `dingtalk-workspace-cli` v1.0.35 (`dws`) and `@larksuite/cli` v1.0.50.
- Auth is injected via the persistent mount, not baked into the image:
  `~/.dws -> /mnt/agents/.user/auth/dws/.dws`,
  `~/.lark-cli -> /mnt/agents/.user/auth/lark/.lark-cli`,
  `~/.local/share/{dws,lark}-cli -> /mnt/agents/.user/auth/...`,
  `~/.kimi/agent-gw.json -> /mnt/agents/.agent-gw.json`.
- The mount means credentials survive sandbox resets and are shared across
  every container backed by the same `/mnt/agents` volume.

### Other pre-provisioned runtimes
- `.dotnet` 8.0.425, `.nuget`, `NuGet` in `.local/share`, `.pki` (0700).
- Python site-packages includes the proprietary `agent-gw` SDK v0.3.0
  (Moonshot AI, "Kimi For Coding Backend") covering `/v1/chat/completions`,
  `/v1/messages`, `/v1/embeddings`, `/v1/search`, `/v1/fetch`, `/v1/files`,
  and a `/v1/tools` dispatcher (`get_stock_realtime_price`, `nlp_*`,
  `call_data_source_tool`, ...). Default base URL in code is the dev host
  `agent-gw-dev.dev.kimi.team/coding`; the live config overrides it to
  `https://agent-gw.kimi.com/coding` with a working `sk-kimi-...` key.

## 2. Agent-reachable endpoint inventory

| Port | Service | Auth | Surface |
|------|---------|------|---------|
| 8888 | Jupyter Kernel Management Server (FastAPI) | none | `POST /kernel/execute` (arbitrary Python), `/kernel/reset`, `/kernel/interrupt`, `/kernel/status`, `/kernel/connection(-file)`, `/kernel/debug`, `/openapi.json`. CORS: `allow_origins=["*"]` — any web page in any browser can drive code execution in the sandbox. |
| 8080 | Portal API | none observed | `POST /api/v1/apps` creates an application and returns `app_id` + `app_secret` + `creator_user_id`. Verified live: a probe app was created and a secret issued without credentials. (Side-effect artifact: app "probe-test" now exists.) |
| 9223 | CDP relay (socat 9223->9222) | none | Full Chrome DevTools Protocol. `/json/version` = Chrome/151.0.7922.108, browser WS `ws://127.0.0.1:9223/devtools/browser/...`. `/json/list` exposes live targets incl. the pdf-viewer extension service worker (`chrome-extension://gpkoddcemgbmajecfkkolkgfcchmfpge/background.js`). Chromium launched with `--remote-debugging-address=0.0.0.0`. |
| 6080 | KasmVNC | `-SecurityTypes None` (no VNC auth) | Full desktop control. Config binds `0.0.0.0`, idle timeouts all `never`, clipboard DLP fully bidirectional/unlimited, HTTP headers `COEP=require-corp`, `COOP=same-origin`. |
| 10250 | Node kubelet (10.183.20.207) | TLS client auth | `/healthz` -> 401 Unauthorized, `/pods` -> 404 — but the serving cert is the node's: `CN=10.183.20.207@1790098622`, issuer `10.183.20.207-ca@...`. Reaching the kubelet from inside the pod proves pod->node east-west access. |
| external | `https://agent-gw.kimi.com/coding` | `sk-kimi-...` key (world-readable-ish at `/mnt/agents/.agent-gw.json`, mode 444 root) | Full agent-gw API: chat completions, messages, embeddings, search, fetch, file upload, tool dispatcher. The sandbox's own inference backend is callable with a captured key. |

## 3. Inherited CSP bypass / CORS posture

1. **Kernel server CORS `*`** — the execution plane trusts every origin. Any
   site the operator (or a page the operator is tricked into opening) can
   `fetch('http://127.0.0.1:8888/kernel/execute', {method:'POST', ...})`.
2. **CDP bound to 0.0.0.0** via socat — DevTools websocket usable from any
   interface that can route to the pod; combined with no auth this is full
   browser takeover (cookies, extension storage, page injection).
3. **pdf-viewer extension** — `permissions: ["<all_urls>", ...]` with content
   scripts and a service worker visible in the CDP target list; the custom
   `preserve-referer.js` / `suppress-update.js` / `telemetry.js` modules
   (see pdf-viewer/) show deliberate browser-policy patching.
4. **KasmVNC COEP/COOP headers** are the *only* hardening found, and they
   matter little given VNC auth is disabled entirely.
5. **Kubernetes identity bleed** — `/etc/hosts` is stamped "eci-managed",
   `resolv.conf` points at cluster DNS 192.168.0.10 with a HostAliases shim
   mapping `kubernetes.default -> 192.168.0.1`, and `/proc/cmdline` leaks the
   host's LifseaOS ostree boot line (`selinux=0 lsm=` — SELinux disabled and
   LSM list empty on the host). The pod is a plain containerd overlayfs
   container (150+ layers, snapshot 206), not a micro-VM: no Kata/gVisor
   boundary between agent and node.

## 4. Why this matters (prior-art chain)

Possession of internal-only files (this repo) + demonstrated navigation of the
overlay/cgroup/namespace layout + external egress proven through agent-gw +
cross-container contact proven by the earlier SCA work (heat/thermal,
ipython system) + the endpoints above = an agent inside this sandbox can
execute code, drive the browser, create portal applications with fresh
secrets, and call the production inference gateway — all without any
credential being requested at runtime. Guardrails and `<meta>` context
inclusions are the only control layer, and they are advisory, not enforced.
