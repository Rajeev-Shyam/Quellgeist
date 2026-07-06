"""Wave-4 comparison-matrix tooling (plan Task 4; measurement riders DR-0020 §8).

One matrix CELL = (reasoner model) x (verifier on/off) x (scenario set), run
for >=3 scored passes with real per-scenario cost instrumentation and
trace-level audits. ``run_cell`` produces one cell's raw records + summary;
``report`` merges cell summaries into the comparison table; ``audits`` holds
the trace-level checks that pass rates cannot see (the corpus has a measured
81/81 script ceiling -- DR-0020 decision 1 of the context).
"""
