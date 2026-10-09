"""Admin task control for a full native LeadTrace checkout.

The scientific runner lives alongside the backend package under leadtrace/ops.
Native ASGI servers start in leadtrace/backend, so resolve the installed checkout
rather than depending on pytest's pythonpath or the caller's working directory.
"""
from pathlib import Path
import sys

_checkout = Path(__file__).resolve().parents[4]
if (_checkout / 'leadtrace/ops/ai_prefill/tasks.py').is_file():
    if str(_checkout) not in sys.path:
        sys.path.append(str(_checkout))
