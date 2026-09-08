#!/usr/bin/env python3
"""Canonical Feynman evaluation aggregation entrypoint.

The historical schema-v2 aggregator is preserved in
`feynman_eval_aggregate_v2_legacy.py`. Canonical aggregation accepts only
analysis-result schema v3, which includes pre-run runner-job linkage.
"""
try:
    from .feynman_eval_aggregate_v3 import aggregate, main
except ImportError:
    from feynman_eval_aggregate_v3 import aggregate, main

__all__ = ["aggregate", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
