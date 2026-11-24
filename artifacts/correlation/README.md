# Correlation model artifacts

The integrated verified experiment is stored under
`backend/data/correlation/experiments/f1_improvement_v3/`; this directory remains
reserved for separately supplied generic artifacts.

When `CORRELATION_PREDICTOR=trained`, provide:

- `model.joblib`: a trusted scikit-learn-compatible artifact exposing `predict_proba`.
- `model_metadata.json`: metadata conforming to [`MODEL_INTEGRATION.md`](../../MODEL_INTEGRATION.md).

For the integrated experiment use `CORRELATION_PREDICTOR=trained_evidence` and the
three paths documented in [`MODEL_INTEGRATION.md`](../../MODEL_INTEGRATION.md).
Missing or invalid artifacts produce an explicit unavailable error; the application
never falls back to the baseline automatically.
