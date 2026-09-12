"""User-selected subscription models, not account access or tool-use claims.

Each new runner job binds exactly one ID. This registry does not change frozen
jobs, install credentials, perform model calls, or implement fallback routing.
"""
from __future__ import annotations

import json

SUBSCRIPTION_WORK_MODELS = (
    'gpt-5.6-luna',
    'gpt-5.6-terra',
    'gpt-5.6-sol',
)


def model_selection_report() -> dict:
    return {
        'schema_version': 1,
        'models': list(SUBSCRIPTION_WORK_MODELS),
        'authentication_mode': 'chatgpt-subscription',
        'api_key_auth_allowed': False,
        'automatic_fallback': False,
        'automatic_model_runs': False,
        'account_availability_verified': False,
        'tool_use_verified_for_all_models': False,
        'selection': 'explicit-one-model-per-new-runner-job',
    }


if __name__ == '__main__':
    print(json.dumps(model_selection_report(), indent=2))
