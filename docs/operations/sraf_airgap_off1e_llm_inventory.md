# SRAF OFF-1E — opt-in localhost Ollama model inventory

The reviewed OFF-1D readiness matrix now supports a **narrowly scoped** additional LLM inventory observation. It **does not** generate prompts, start an Agent, authenticate to a model host, test a remote HTTPS endpoint, call a proxy, validate inference quality or certify FULL_LIVE deployment acceptance.

From the actual deployed repository root:

```bash
# Default: no network access
python tools/sraf_airgap_off1d_readiness_matrix.py

# Existing bounded TCP + API health only; no model inventory
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network

# Optional additional Ollama inventory over localhost
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-llm-inventory
```

The inventory flag **does nothing without** `--probe-network`. The independent configured LLM TCP check must first PASS. The matrix then validates that `MODEL_BASE_URL` resolves to the exact numeric `127.0.0.1` loopback using anonymous `http`, with no arbitrary prefix: root, `/api/chat` or `/api/generate` are supported. Public IPs, private remote IPs, other loopback addresses, DNS, HTTPS and reverse-proxy prefixes are skipped instead of silently probed. The model is the *effective runtime* `MODEL_ID`, not a user-supplied CLI model or hardcoded example.

The tool reuses the OFF-1A strict three-second absolute-deadline, 64-KiB maximum, one-request `GET http://127.0.0.1:{port}/api/tags` implementation. It never follows redirects or sends authorization credentials. A real PASS requires HTTP 200, a valid bounded inventory object with the configured model name, affirmative model availability, reviewed probe identity and consistent returned status. Output contains only a fixed `LLM-INVENTORY` row (PASS/FAIL/SKIP/NOT_TESTED, safe reason and dependencies), without model names, URLs, ports, response documents, counts, tokens or credentials. Unexpected provider PASS metadata never upgrades acceptance. Explicit FAIL retains its severity and is redacted.

This is **a local Ollama inventory check only**. A missing model is FAIL; unsupported destination or auth-required inventory is SKIP; without deliberate opt-in it stays NOT_TESTED. `LLM-INFERENCE`, actual SQL read, ES identity/Mapping, workers, Word and physical isolation remain NOT_TESTED even if the model is listed. The overall CLI still exits 1 for observed failures, otherwise 2 for incomplete acceptance; it never emits success code zero or a FULL_LIVE verdict.

Hosted CI tests use deterministic mocked network boundaries and are **not** private SRAF Linux acceptance. Existing production deployment and credentials are untouched.
