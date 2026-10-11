# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Agent OS control service (skeleton).

Deterministic local control plane: SQLite operational truth, append-only
event log, human-only approval decisions, deny-before-dispatch policy.

No real runtime (Hermes/DSH/Antigravity) is connected at this stage.
"""

__version__ = "0.2.0"
