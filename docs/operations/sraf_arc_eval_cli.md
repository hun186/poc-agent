# ARC A9 private offline evaluation CLI

From a locally deployed repository with existing Python dependencies installed:

```bash
python -m agent.es.evidence_core.arc_eval_cli semantic PRIVATE_LABELS.json
python -m agent.es.evidence_core.arc_eval_cli selection PRIVATE_SELECTION.json
```

Input is a local UTF-8 (optional BOM) JSON file containing the case arrays
described in sraf_arc_semantic_eval.md and sraf_arc_selection_eval.md.
No network, ES, model, production output change, fixture creation or
automatic rollout. Maximum file read 2 MiB plus one byte, strict duplicate
JSON key rejection and existing evaluator limits. Invalid, unreadable,
oversized or malformed files fail with exit code 2 and a fixed diagnostic;
successful offline aggregation exits 0 and emits a JSON summary to stdout.
Neither file path nor input values are echoed on error. A successful run
does not certify the quality or completeness of the operator's annotation
or authorize deployment. Keep real fixtures on the private host, not in
Git, CI artifacts, shared cloud folders or application logs.
