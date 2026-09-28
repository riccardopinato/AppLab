# AppLab v2.7 — Behavioral Product Lab

Behavioral Product Lab reconciles the static Product Flow Graph with trusted runtime
evidence already collected by AppLab's Safe Interaction Crawler.

It records safe controls exercised, observed UI-state changes, runtime failures and
static surfaces that were or were not matched during bounded exploration.

## Guardrails
- only existing conservative crawler actions are consumed;
- an unobserved surface is not declared unreachable;
- runtime failures remain traceable to runtime evidence;
- this layer cannot change FAST/FULL/CERTIFICATION verdicts.
