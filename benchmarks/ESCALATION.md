# Escalation log

## arithmetic (one round)

Initial 12 samples scored avg_score >= 0.95 on every model/effort combo, so 5 harder samples were appended (total 17).

Added:
- `7^6 - 5^8 + 3^9` → -253293
- `1 + 1/(1 + 1/(1 + 1/2))` → 1.6
- `(13^3 - 11^3) / (13 - 11)` → 433
- `2^20 / 2^10 - 3^5` → 781
- `(9/4 + 7/6) * (18/5) - 11/10` → 11.2

Final published results use the escalated 17-sample set.

## differential (one round)

Initial 10 samples scored avg_score 1.0 on every combo (some API capacity errors on individual samples). Added 4 harder samples (total 14).

Terminal was not escalated; the suite is the 16-sample set described in README.md (including zip / ln / mkfifo).
