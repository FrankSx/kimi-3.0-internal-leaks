# Kimi Platform Internals — Comparative Analysis: 2.0 → 2.5 → Current (Sept 2026)

**Sources**:
- `FrankSx/kimi-2.0-internal-leaks` (GitHub, archived June 2026): `browser_guard.py`, `kernel_server.py`, `jupyter_kernel.py`, `utils.py`, `pdf-viewer/` extension
- `FrankSx/Kimi-2.5-internal-leaks` (GitHub, archived April 2026): `docx/`, `pdf/`, `webapp-building/` skills + `SystemInternals/` recon
- **Live environment** (sandbox, probed 2026-09-22): current versions of all of the above, running

**Method**: byte-level diffs of archived files against live `/app` counterparts, structural diff of skill trees, fresh system recon replayed against the 2.5 `SystemInternals` snapshot.

---

## 1. Executive Summary

| Layer | 2.0 → 2.5 → Current | Verdict |
|---|---|---|
| browser_guard.py | 28,185 B → **byte-identical today** | Frozen since 2.0 |
| utils.py | 1,252 B → **byte-identical today** | Frozen since 2.0 |
| kernel_server.py | +73 lines | **New `/kernel/execute` endpoint** |
| jupyter_kernel.py | +321 lines | Init externalized, timeout-interrupt hardening |
| pdf-viewer ext. | partial dump → full viewer | Expanded (viewer.html/mjs, locales, fonts) |
| Skills | 3 sampled → **271 skills + 16 plugins** | Massive ecosystem expansion |
| docx skill | Python editing lib → **15 MB stripped native .so** | Engine went compiled (analysis-resistant) |
| pdf skill | routes unchanged in count | `doctor` preflight + ReportLab fallback added |
| webapp-building | repo-local templates → **Portal-mounted templates + traversal/symlink hardening** | Security fixes (notable) |
| Workdir | `/mnt/okcomputer` → `/mnt/agents` | Renamed platform-wide |
| Skills root | `/app/.kimi/skills` → `/app/.agents/skills` | Renamed platform-wide |
| Kernel | `5.10.134-18.0.9` (Jan 2026) → `5.10.134-18.0.12` (Aug 2026) | Minor bump, same lifsea base |
| Chromium | older build, `--enable-automation` → **151.0.7922.108, flag removed** | Automation flag dropped |
| Egress proxy | `10.86.13.73:5900` → **same proxy** | Unchanged since 2.5 |
| SSH authorized key | `moonshot@space.local` → **same key** | Unchanged across all eras |

---

## 2. System Layer

### 2.1 Kernel & OS
- **2.5 (Jan 2026)**: `Linux k2025964575489474561 5.10.134-18.0.9.lifsea8.x86_64 #1 SMP Fri Jan 23 16:08:32 CST 2026`
- **Live (Sept 2026)**: `Linux k2102332857861140480 5.10.134-18.0.12.lifsea8.x86_64 #1 SMP Tue Aug 4 16:35:16 CST 2026`
- Same Debian 12 (bookworm), same `uid=999(kimi) gid=995(kimi)`, same `TZ=Asia/Shanghai`. Kernel went `18.0.9 → 18.0.12` — patch-level bump on Alibaba's lifsea kernel line, no major version change. Hostname scheme unchanged (`k<digits>`).

### 2.2 Platform paths renamed
| 2.5 era | Current |
|---|---|
| `/mnt/okcomputer` (PWD) | `/mnt/agents` |
| `/app/.kimi/skills` | `/app/.agents/skills` |
| — | `/app/.user/skills` (new: user-created skills) |
| — | `/app/.agents/plugins` (new: plugin system) |

### 2.3 Environment variables
New in live: `NODE_PATH=/home/kimi/.npm-global/lib/node_modules`, `NPM_CONFIG_REGISTRY=https://npm.mirrors.msh.team/` (Moonshot's internal npm mirror — also explains why public npm/pypi are unreachable from inside), expanded PATH with four skill template `.bin` dirs (`webapp-building`, `webapp-building-swarm`, `backend-building`, `backend-building-swarm`) and `/app/.ppt`.

---

## 3. Network & Egress

### 3.1 Listeners — then vs now
| Port | 2.5 | Live | Service |
|---|---|---|---|
| 22 | ✓ | ✓ | sshd (`AllowUsers kimi`, pubkey only) |
| 8888 | ✓ (PID 51 python3) | ✓ (PID 60 python3) | **kernel_server.py** |
| 9222 | ✓ (chromium, localhost) | ✓ (chromium, localhost) | CDP |
| 9223 | ✓ (0.0.0.0) | ✓ (0.0.0.0) | **socat → 9222 CDP forward** |
| 10250 | ✓ | ✓ | kubelet (K8s node agent) |
| 6080 | ✓ | ✓ | KasmVNC websocket |
| 8080 | ✓ (tcp6) | ✓ (tcp6) | — |
| random high ports on pod IP | many (PIDs 138/337) | several (PID 138) | ipykernel ZMQ channels |

The **service topology is essentially unchanged** — same s6 supervision tree (`s6-svscan` → `kasmvnc`, `sshd`, `kernel-server`, `browser-guard`, `socat`), same KasmVNC on `:99` with `-SecurityTypes None`, same socat CDP relay.

### 3.2 Egress
- Chromium runs with `--proxy-server=10.86.13.73:5900` in **both** the 2.5 capture and live — the forced-egress proxy predates the 2.5 sampling. Direct internet (github.com) from shell is intermittent/filtered; package mirrors point at `*.mirrors.msh.team`.

---

## 4. Core Services — Byte-Level Diffs

### 4.1 `browser_guard.py` — UNCHANGED
28,185 bytes, byte-identical between the 2.0 archive and `/app/browser_guard.py` (mtime Aug 12 2026). Runs as `python3 /app/browser_guard.py --wait-display --display :99 --timeout 60 --monitor`. Whatever it enforces, it has been frozen for the entire 2.0→current span.

### 4.2 `utils.py` — UNCHANGED
1,252 bytes, byte-identical.

### 4.3 `kernel_server.py` — NEW EXECUTE ENDPOINT
The 2.0 version exposed only kernel **reset / interrupt / connection-file query**. The live version adds:

```python
@app.post("/kernel/execute", response_model=KernelExecuteResponse)
async def execute_kernel(request: KernelExecuteRequest):
    # code: str, timeout: float (default 30), restart: bool
```

- Full code execution over HTTP on `0.0.0.0:8888` with an `asyncio.Lock` serializing execution
- Optional `restart=true` resets the kernel before running
- Gates on `run_init_script_if_needed()` — init script failures now block execution with 500
- All blocking kernel calls wrapped in `asyncio.to_thread` (2.0 called them synchronously)

This endpoint is the backend of the current in-chat Python tool — in 2.0, execution went through a different path and the server was management-only.

### 4.4 `jupyter_kernel.py` — INIT EXTERNALIZED + TIMEOUT HARDENING
- The inline matplotlib/CJK-font init block (a big embedded string in 2.0) moved to a sibling file **`ipython.py.init`** (new), loaded via `IPYTHON_INIT_SCRIPT_PATH` and executed lazily on first use (`_init_script_pending` flag)
- New init also registers `ImageShow.IPythonViewer` for PIL and sets a pastel color cycle — cosmetics, but confirms this file is the current chart-style source
- **Timeout behavior rewritten**: 2.0 returned a timeout error and left the kernel busy; live calls `interrupt_kernel()` and then drains IOPub until `execution_state == idle` — a hung cell can no longer wedge the session
- `execute()` timeout widened `int → float`

### 4.5 pdf-viewer extension
The 2.0 archive was a partial dump. Live `/app/pdf-viewer` (loaded into Chromium via `--load-extension=/app/pdf-viewer`) now contains the full PDF.js viewer (`content/web/viewer.html`, `viewer.mjs`, `locale/`, `standard_fonts/`, `cmaps/`, icons). Shared files (`contentscript.js`, `preserve-referer.js`, `suppress-update.js`, `telemetry.js`, `contentstyle.css`) all differ — the extension is actively maintained.

---

## 5. Chromium — Flag-Level Diff

2.5: `--enable-automation` present, `RenderDocument` in disable-features.
Live (151.0.7922.108):

```
- --enable-automation                     REMOVED
- RenderDocument                          REMOVED from disable-features
+ --disable-edgeupdater                   ADDED
+ --disable-updater-scheduler             ADDED
+ BlockOriginHeaderModificationOnRedirect ADDED to disable-features
+ msForceBrowserSignIn, msEdgeUpdateLaunchServicesPreferredVersion ADDED
```

**Kept across both eras**: `--no-sandbox` (twice), `--single-process`, `--remote-debugging-port=9222` + `--remote-debugging-pipe`, `--disable-blink-features=AutomationControlled`, `--proxy-server=10.86.13.73:5900`, `--user-data-dir=/app/data/chrome_data`, `--js-flags=--max_old_space_size=1024`.

Dropping `--enable-automation` while keeping `AutomationControlled` disabled is an anti-detection refinement — the browser no longer self-identifies as automated in the `navigator.webdriver`-adjacent surface, while the Blink-level automation markers stay suppressed.

---

## 6. SSH

- `sshd_config` effective config identical in spirit: `PermitRootLogin no`, pubkey-only, `AllowUsers kimi`, `X11Forwarding yes`
- **The authorized key is the same across eras**: `ssh-ed25519 AAAAC3...tVO moonshot@space.local` — the platform's control-plane key has not been rotated between the 2.5 capture and today
- `SetEnv` line expanded: added `NPM_CONFIG_REGISTRY`, `NODE_PATH`, and the four template `.bin` paths

---

## 7. Skills Ecosystem — The Big Explosion

| | 2.5 archive (Apr 2026) | Live (Sept 2026) |
|---|---|---|
| Skills root | `/app/.kimi/skills` | `/app/.agents/skills` |
| Skills | 3 sampled (docx, pdf, webapp-building) | **271** |
| Plugins | n/a | **16** (github, gmail, kimi-word, kimi-pdf, kimi-excel, scholar, sec_edgar, yahoo_finance, world_bank, imf, igo_open_data, image/audio/video_generation, email, musepool) |
| User skills | n/a | 6 |

The 271 live skills span finance, writing, research, slides, design, security (`web-security-audit`, `code-vuln-audit`, `secure-code-review`), K8s (`kubectl`, `k8s-cluster-ops`), browser automation (`browse`, `fast-browser-use`, `playwright-scraper-skill`, `rust-browser-pilot`), and swarm variants (`webapp-building-swarm`, `deep-research-swarm`, `vibecoding-webapp-swarm`).

### 7.1 webapp-building — security hardening (the most interesting diff)

`init-webapp.sh`, 2.5 → live:

```diff
- TEMPLATE_PATH="$REPO_ROOT/templates/$TEMPLATE_NAME"
+ WEBSITE_TEMPLATES_ROOT="/mnt/agents/.websites-templates"   # Portal-mounted read-only
+ [[ ! "$TEMPLATE_NAME" =~ ^[A-Za-z0-9_-]+$ ]] && exit 1     # NEW: name whitelist
+ MOUNT_ROOT_REAL="$(cd -P "$WEBSITE_TEMPLATES_ROOT" && pwd)"
+ TEMPLATE_PATH_REAL="$(cd -P "$TEMPLATE_PATH" && pwd)"
+ [[ "$TEMPLATE_PATH_REAL" != "$MOUNT_ROOT_REAL/"* ]] && exit 1  # NEW: containment check
+ [[ -L "$TEMPLATE_ZIP" ]] && exit 1                         # NEW: symlink rejection
+ [[ -L "$INFO_MD" ]] && exit 1                              # NEW: symlink rejection
```

This is a **path-traversal + symlink-escape fix**: in 2.5, `template-name` was concatenated straight into a path with no validation (`../../etc` would have been accepted), and templates shipped inside the skill repo. Now templates come from a read-only Portal mount, names are whitelisted, resolved paths must stay inside the mount, and symlinks are rejected outright. Also a bug fix: the 2.5 Darwin branch read `sed -i ''` — live reads `sed -i` (the "macOS support" was decorative; this is a Linux-only sandbox).

The live SKILL.md also adds a long **"Product Knowledge"** section documenting the delivery pipeline: version saving = delivery, preview vs publish distinction, `ok.kimi.link` subdomains, Kimi OAuth via backend-building, "never route users to external hosts".

### 7.2 docx — the engine went native

2.5: pure-Python editing library (`scripts/docx_lib/editing/{comments,revisions,context,helpers,xml_tolerance}.py`, `element_order.py`, `business_rules.py`) + monolithic 32 KB SKILL.md.

Live: the editing core is **`scripts/engine/_core.cpython-312-x86_64-linux-gnu.so` — a 15 MB stripped ELF shared object** (plus a second copy under `docx_lib/`). The Python editing sources are gone. SKILL.md shrank 32 KB → 7.8 KB and became a routing document pointing at six reference files (`wir-reference.md`, `openxml-sdk-reference.md`, `md2docx-reference.md`, `omml-reference.md`, `chart-reference.md`, `matplotlib-guide.md`). New `md2docx/` pipeline (citation parser, footnotes/endnotes, postprocess).

Interpretation: the WIR editing engine was rewritten in a compiled language (size + stripped + PyO3-style naming suggests Rust) — faster, and **no longer readable as source**. The 2.5 Python sources in the archive are now the only public copy of that logic.

### 7.3 pdf — preflight discipline

File tree identical between 2.5 and live; all content files differ. Key changes:
- New mandatory preflight: `python3 ./scripts/pdf.py doctor` probes Node+Playwright+browser before choosing a creation route
- New **ReportLab fallback route** (`routes/reportlab.md`) for browser-less environments
- New **Markdown-first handoff** section: Deep Research Markdown + `citation.jsonl` (`/mnt/agents/.store/citation.jsonl`) treated as canonical input, `[^123^]` markers mapped to source IDs, "never fabricate or silently delete a source"
- Hardcoded `/app/.kimi/skills/pdf/...` paths replaced with relative `./scripts/...`

---

## 8. Security Posture Assessment

### Hardened since the archives
1. **Template path traversal/symlink escape in webapp-building** — closed (whitelist + containment + symlink rejection). This class of fix usually follows observed abuse.
2. **Kernel timeout wedge** — a hung cell in 2.0 left the kernel permanently busy; now interrupt+drain.
3. **Chromium automation self-identification** — `--enable-automation` removed.
4. **Init-script failure propagation** — kernel init failures now surface as 500 instead of silent state corruption.

### Unchanged / still exposed
1. **`/kernel/execute` on 0.0.0.0:8888** — unauthenticated code execution endpoint; the 2.0 management-only server is now a full RCE-by-design service (by design for the agent, but anything reaching the pod IP gets it).
2. **CDP relay on 0.0.0.0:9223** — socat forwards Chromium DevTools to all interfaces; Chromium still `--no-sandbox --single-process`.
3. **KasmVNC `-SecurityTypes None -DisableBasicAuth`** on 6080.
4. **Same SSH control-plane key** (`moonshot@space.local`) across at least 8 months of captures.
5. **browser_guard.py frozen since 2.0** — whatever bypasses existed against the 2.0 guard logic still apply verbatim; the archived copy is a current reference.
6. **Kubelet 10250 listening** on pod IP (matches earlier ACK/Kata recon).

---

## 9. Repository Layout

```
kimi-3.0-internal-leaks/
├── README.md                        ← prior-art statement & chain of custody
├── ANALYSIS.md                      ← this report
├── system/                          ← live /app service files (3.0 capture)
│   ├── browser_guard.py  kernel_server.py  jupyter_kernel.py  utils.py  ipython.py.init
├── recon_live/                      ← fresh capture: system/env/network/processes/
│                                     sshd_config/authorized_keys/skills_list/plugins_list
├── diffs/                           ← all unified diffs (2.0→live, 2.5→live)
├── skills/                          ← current skill entry files
│   ├── docx/SKILL.md  pdf/SKILL.md  webapp-building/SKILL.md + scripts/init-webapp.sh
└── pdf-viewer/                      ← current bundled PDF.js extension core files
```

Full raw staging trees (both archives + complete live skill trees including the 15 MB native docx engine `.so`) are preserved in the sandbox deliverable `Kimi_Platform_Baseline_2.0-2.5-Current.zip` (972 files, 31 MB); `node_modules` directories are excluded as rebuildable. The 2.0/2.5 upstream snapshots remain available at their original GitHub repos and are not duplicated here.
