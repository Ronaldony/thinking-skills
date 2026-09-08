#!/usr/bin/env python3
"""Canonical Feynman analysis-result entrypoint.

Schema v2 is preserved in `feynman_eval_result_v2_legacy.py` for historical
reproduction only. New analysis-ready results must use schema v3 and bind the
pre-execution runner job through a verified runner-job-link artifact.
"""
try:
    from .feynman_eval_result_v3 import assemble, main
except ImportError:
    from feynman_eval_result_v3 import assemble, main

__all__ = ["assemble", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
