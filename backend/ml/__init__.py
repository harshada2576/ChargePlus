"""ChargePlus — Data mining, forecasting & recommendations (Phase 5/6).

Methodology-first: every data-dependent step enforces evidence gates
(gates.py) before touching data. With a COLD warehouse, training and
prediction correctly refuse; specifications, baselines, features, and
contracts are implemented and fixture-tested so Phase 5 activates
naturally when real temporal evidence arrives. No synthetic production
data, ever.
"""

from backend.ml.gates import evaluate_gates

__all__ = ["evaluate_gates"]
