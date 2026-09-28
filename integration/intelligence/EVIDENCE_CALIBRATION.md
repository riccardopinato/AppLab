# AppLab v2.9 — Evidence Calibration Engine

Evidence Calibration reconciles Product Consistency findings with Behavioral Product
and State & Edge-Case runtime evidence.

Evidence classes:
- RUNTIME_CONFIRMED
- RUNTIME_CORROBORATED
- STATIC_CORROBORATED
- STATIC_HEURISTIC
- RUNTIME_CONTRADICTED

Contradicted static findings are suppressed for action, not deleted from evidence.
No numeric quality score is generated and certification authority is unchanged.
