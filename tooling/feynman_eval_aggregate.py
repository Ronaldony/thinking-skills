#!/usr/bin/env python3
"""Canonical Feynman aggregate interface (accepts result schema v4 only)."""
try:
    from .feynman_eval_aggregate_v4 import *  # noqa: F401,F403
except ImportError:
    from feynman_eval_aggregate_v4 import *  # noqa: F401,F403
