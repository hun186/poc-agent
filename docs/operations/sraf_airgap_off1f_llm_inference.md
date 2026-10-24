# SRAF OFF-1F — explicitly authorized bounded localhost LLM inference

This operator-only partial observation builds on merged OFF-1D/1E readiness probes. It is **not** automatic deployment acceptance, Report Job execution, model quality testing, authentication, a ChatGPT-compatible API, an Agent invocation, or an Elasticsearch/SQL/Word test.

## How to run on the authorized Linux host

From the deployed repository root:

```bash
# Default: zero network requests, zero LLM inference
python tools/sraf_airgap_off1d_readiness_matrix.py

# Existing bounded TCP/health + optional local model inventory
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory

# CAUTION: requires the actual running Ollama serve PID.
# Run only if you verified the server was started with OLLAMA_NO_CLOUD=1.
# The probe independently checks the PID's socket and environment.
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory --probe-llm-inference --ollama-server-pid <OLLAMA_SERVE_PID>
```

There must be three explicit flags. The configured `MODEL_BASE_URL` must be exact, numeric `http://127.0.0.1:<port>` with root, `/api/chat`, or `/api/generate` only; DNS, IPv6, other loopback IPs, private remote IPs, HTTPS, custom proxy prefixes, username/password in URLs and public addresses are **not probed** for inference. LLM TCP must pass the previously reviewed private/loopback endpoint validation. An actual verified Ollama inventory observation must report the configured `MODEL_ID` present. A failed or skipped inventory prevents generation.

OFF-1F then makes **one** anonymous, fixed-path `POST /api/generate` to the same loopback port, with a fixed benign English prompt, `stream:false`, `num_predict:8`, `num_ctx:512`, temperature zero. User prompt text is not accepted by the CLI. Body is bounded to 1024 bytes. The reused strict HTTP parser enforces an absolute 20-second local client deadline, max 64-KiB response, strict HTTP framing, identity/no Content-Encoding and no redirect following. It uses no authentication, DNS, proxies, external URL or retries. This **can start loading a large Ollama model and consume substantial CPU/GPU RAM** despite only requesting a few generated tokens. A client timeout does **not** guarantee the server cancels or unloads its work; inspect local Ollama resource usage yourself. No `keep_alive` is overridden and no process is stopped.

For a limited positive observation, HTTP must be 200, valid bounded JSON, matching requested model identity in the returned claim, `done=true`, a nonempty answer, and an integer generated-token count from 1–8. A positive result means only **a bounded Ollama generation response was observed**, not answer quality, model identity cryptographic attestation, semantic correctness, throughput, LLM pipeline integration, RAG, SQL connectivity, worker identity or DOCX generation. Server output, model name, prompt, URL, headers, response body, token counts and credentials never appear in the summary.

Non-200 errors can be FAIL; explicit rate limiting/auth/cold-start/network uncertainty is SKIP rather than successful execution. An inconsistent nominal PASS is downgraded. `LLM-INFERENCE` is `NOT_TESTED` unless all flags were set; unrelated SQL/ES/Workers/Word/air-gap entries remain `NOT_TESTED`. The matrix never emits FULL_LIVE or exit 0: exit 1 means observed failures, exit 2 incomplete verification.

Hosted CI tests stub all generation/network calls; a green Hosted CI does **not** establish access to or successful inference on your actual private Linux server. Actual operator invocation requires prior deployment permission and sufficient memory/GPU headroom.

## P1 security remediation — block cloud-backed inference *before* POST

The original three-flag OFF-1F design is **insufficient** to guarantee local computation. The Ollama loopback server can forward a cloud-backed model (or local alias) to a remote host. A `127.0.0.1` HTTP request and an inventory PASS do **not** establish local inference. Merely rejecting returned `remote_host` metadata would be too late because the prompt could already have left the machine.

**OFF-1F now fails closed** without an additional operator-specified `--ollama-server-pid` identifying the actual `ollama serve` process on the Linux deployment host. Before any generation POST, the probe reads *only fixed Linux /proc paths* and verifies:

1. The supplied PID's executable and argv identify `ollama serve`.
2. That same process owns the **exact** IPv4 `127.0.0.1:<configured-port>` LISTEN socket inode (wildcard, IPv6, proxy, different owner and ambiguous listeners are rejected).
3. The **running server process environment** contains exactly `OLLAMA_NO_CLOUD=1`. An `OLLAMA_NO_CLOUD` value in the *probe process*, a stale server.json file or a verbal claim does not qualify.
4. One bounded anonymous localhost `GET /api/version` confirms Ollama at least v0.16.2, the release supporting `OLLAMA_NO_CLOUD`; missing/old/invalid versions are rejected. The process/socket proof is checked again before POST.

See <https://github.com/ollama/ollama/blob/main/docs/faq.mdx> and <https://github.com/ollama/ollama/blob/main/envconfig/config.go> for upstream no-cloud functionality. To enforce no cloud, set the environment variable **on the Ollama service** before starting it, restart that service, then identify the service PID; setting it only in the SRAF or operator shell is ineffective. This PR does not change your Ollama service settings and never restarts it.

If the Ollama service PID, executable, process environment or socket are hidden (e.g. separate Docker PID namespace), unverifiable, or the server only reads no-cloud from server.json, the probe returns **SKIP / `llm_inference_cloud_disable_unverified` before POST**. This conservative limitation is intentional: do not bypass it by trusting a model name, a local inventory result, a different process environment or a container's port forwarding.

A generation response containing `remote_host` or `remote_model` is independently marked SKIP as defense in depth; response inspection alone does **not** prevent a cloud request. The trusted local machine must not be controlled by a malicious same-host root process; /proc inspection and network connection are sequential and cannot cryptographically attest immutable host state or eliminate hostile process replacement races.

An additional loopback version GET is performed only after the explicit flags, PID and initial local process check. The old one-POST/no-retry inference policy remains; total incremental network reads are one inventory GET, one version GET and a single conditional generation POST (plus the previously documented baseline TCP/health checks). The 20-second client deadline applies to the POST only. Version probing is a bounded three-second GET.

A model may still consume CPU/GPU and memory, and client timeout does not terminate server work. Actual operator-host validation, network isolation and complete production SRAF acceptance remain separate.
