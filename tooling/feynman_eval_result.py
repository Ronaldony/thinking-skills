#!/usr/bin/env python3
"""Canonical Feynman analysis-result interface (schema v4)."""
try:
    from .feynman_eval_result_v4 import *  # noqa: F401,F403
except ImportError:
    from feynman_eval_result_v4 import *  # noqa: F401,F403
