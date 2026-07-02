"""DR-0020 training-data pipeline (Wave 4, Task 2).

Everything under this package is TRAINING-side: the trajectory builder, the
zero-contamination checks, and the two never-trained probe sets. It lives
outside ``evals/scenarios/`` so ``QG_SCENARIOS_DIR`` globbing can never pick a
training artifact up as an eval item (DR-0020 decision 2).
"""
