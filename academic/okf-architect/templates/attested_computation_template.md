---
type: Attested Computation
title: Sanctioned Metric Calculation
description: The single authoritative calculation method for computing this metric.
tags: [metrics, attestation]
status: stable
runtime: python
parameters:
  - name: start_date
    type: string
    required: true
  - name: end_date
    type: string
    required: true
executor:
  resource: references/executors/run_metric.py
attester:
  resource: references/attesters/verify_receipt.py
generated:
  by: okf-architect/v0.2
  at: 2026-10-13T00:00:00Z
verified:
  - by: human:lead-engineer
    at: 2026-10-13T00:00:00Z
---

# Calculation Definition

Defines the mathematical or procedural definition for computing this metric.

# Computation

```python
def calculate(start_date: str, end_date: str) -> float:
    # Authoritative calculation
    return 100.0
```
