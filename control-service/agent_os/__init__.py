"""Agent OS control service (skeleton).

Deterministic local control plane: SQLite operational truth, append-only
event log, human-only approval decisions, deny-before-dispatch policy.

No real runtime (Hermes/DSH/Antigravity) is connected at this stage.
"""

__version__ = "0.2.0"
