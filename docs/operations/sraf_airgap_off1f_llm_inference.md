# SRAF OFF-1F — explicitly authorized bounded localhost LLM inference

This operator-only partial observation builds on merged OFF-1D/1E readiness probes. It is **not** automatic deployment acceptance, Report Job execution, model quality testing, authentication, a ChatGPT-compatible API, an Agent invocation, or an Elasticsearch/SQL/Word test.

## How to run on the authorized Linux host

From the deployed repository root:

```bash
# Default: zero network requests, zero LLM inference
python tools/sraf_airgap_off1d_readiness_matrix.py

# Existing bounded TCP/health + optional local model inventory
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory

# CAUTION: triggers one real model computation and possible model loading
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory --probe-llm-inference
```

There must be three explicit flags. The configured `MODEL_BASE_URL` must be exact, numeric `http://127.0.0.1:<port>` with root, `/api/chat`, or `/api/generate` only; DNS, IPv6, other loopback IPs, private remote IPs, HTTPS, custom proxy prefixes, username/password in URLs and public addresses are **not probed** for inference. LLM TCP must pass the previously reviewed private/loopback endpoint validation. An actual verified Ollama inventory observation must report the configured `MODEL_ID` present. A failed or skipped inventory prevents generation.

OFF-1F then makes **one** anonymous, fixed-path `POST /api/generate` to the same loopback port, with a fixed benign English prompt, `stream:false`, `num_predict:8`, `num_ctx:512`, temperature zero. User prompt text is not accepted by the CLI. Body is bounded to 1024 bytes. The reused strict HTTP parser enforces an absolute 20-second local client deadline, max 64-KiB response, strict HTTP framing, identity/no Content-Encoding and no redirect following. It uses no authentication, DNS, proxies, external URL or retries. This **can start loading a large Ollama model and consume substantial CPU/GPU RAM** despite only requesting a few generated tokens. A client timeout does **not** guarantee the server cancels or unloads its work; inspect local Ollama resource usage yourself. No `keep_alive` is overridden and no process is stopped.

For a limited positive observation, HTTP must be 200, valid bounded JSON, matching requested model identity in the returned claim, `done=true`, a nonempty answer, and an integer generated-token count from 1–8. A positive result means only **a bounded Ollama generation response was observed**, not answer quality, model identity cryptographic attestation, semantic correctness, throughput, LLM pipeline integration, RAG, SQL connectivity, worker identity or DOCX generation. Server output, model name, prompt, URL, headers, response body, token counts and credentials never appear in the summary.

Non-200 errors can be FAIL; explicit rate limiting/auth/cold-start/network uncertainty is SKIP rather than successful execution. An inconsistent nominal PASS is downgraded. `LLM-INFERENCE` is `NOT_TESTED` unless all flags were set; unrelated SQL/ES/Workers/Word/air-gap entries remain `NOT_TESTED`. The matrix never emits FULL_LIVE or exit 0: exit 1 means observed failures, exit 2 incomplete verification.

Hosted CI tests stub all generation/network calls; a green Hosted CI does **not** establish access to or successful inference on your actual private Linux server. Actual operator invocation requires prior deployment permission and sufficient memory/GPU headroom.
