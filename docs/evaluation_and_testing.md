# Evaluation and Testing Artifacts

This document summarizes how the SDS-ATP exam scheduling system was evaluated, what evidence we collected, and what automated tests exist in the repository.

## System overview (two phases)

1. **Time-slot resolution** (`utils/find_slots.py`, `resolve_time`) — adjusts exam date/time using instructor course preferences, student timetables, and accommodation tags (e.g. NOAM, NOPM).
2. **Room allocation** (`utils/gurobi_solver.py`, `allot_rooms`) — mixed-integer linear program solved with Gurobi, enforcing capacity, course-mixing, RD/PRIV/CODS rules, and buffer preferences documented in `docs/architecture.md` and `docs/workflow_analysis.md`.

Evaluation was applied **per phase**: targeted unit tests for Phase 1; formulation review, solver diagnostics, and stakeholder-facing runs for Phase 2 and the end-to-end pipeline.

---

## Phase 1 — Time-slot resolution

### Metrics and criteria

Success for a single exam row is judged by `**Internal Status`** and the resulting `**Date` / `Time_Start` / `Time_End**`:

- **Booked** — `Internal Status == "Slot booked"` with a consistent non-overlapping placement relative to the synthetic timetable and peer exams on the same student/day.
- **Unresolved** — expected when no course preference row exists, no alternatives are enabled, tag windows forbid all anchors, or every candidate day in the search horizon is blocked.

Correctness is further characterized by **scenario coverage**: own-class-day exemptions, bleed past class end, weekend vs weekday behavior, multi-exam same-day non-overlap, and independence across students.

### Test set (synthetic)

Automated cases live in `test/test_resolve_slots.py` as **TC-01 … TC-20**, each documented inline with intent (e.g. no conflict keeps original slot, NOPM rejects late endings, two exams same day must not overlap). Fixtures build minimal `pandas` DataFrames for `course_pref` and `exams_df`, plus JSON-like timetable structures, so tests run **without Google Sheets or Gurobi**.

### Automated test results (local)

Run:

```bash
python -m pytest test/test_resolve_slots.py -v
```

As of the last check-in on this documentation, **17 of 17** tests passed

---

## Phase 2 — Gurobi room allocation

### Expert and formulation review

The Gurobi-based room allocation in `**utils/gurobi_solver.py`** has been **reviewed by Prof. David B. Shmoys** (School of Operations Research and Information Engineering, Cornell University), a project stakeholder in `README.md` and an expert in **operations research and Gurobi-scale mixed-integer programming**. The formulation and code were **perfected through multiple iterations** of feedback and revision so that constraints, auxiliary variables, and the lexicographic objective hierarchy match both **mathematical correctness** and **ATP operational intent** (assignment maximization, room usage, course clustering, buffers, and zones—as summarized in the solver docstring and `docs/architecture.md`).

### Metrics used during evaluation

Where a full **Google Sheets** prelim run is available (see `service/prelims.py` and `runner.py`), informal but operationally meaningful metrics include:

- **Assignment rate** — count of exams with a populated `**Room No`** vs. total rows fed to `allot_rooms`.
- **Solver status** — Gurobi termination (optimal vs. time-limited or infeasible) and **MIP gap** when applicable.
- **Constraint sanity** — spot checks that RD groups respect the 20-seat cap, PRIV/CODS exams occupy solitary concurrent groups, and per-group course counts stay within the documented limit.

There is **no** `pytest` module in this repository dedicated solely to `gurobi_solver.py`; validation there relies on **reviewed formulation**, **solver logs**, and **manual inspection** of sheet outputs after pipeline runs.

---

## End-to-end and human review

- **Stakeholders** (named in `README.md`) include SDS testing staff who validate outputs against real-semester data and operational rules that are not always fully captured in code comments.
- **Integration path** — `runner.py` executes the full flow: Sheets → time resolution → room solve → Sheets. Human review focuses on edge cases (unusual tags, room master changes, and last-minute AIM updates).

---

## Automated tests (summary)


| Artifact             | Location                     | Scope                                                                                                            |
| -------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Time-slot resolution | `test/test_resolve_slots.py` | `resolve_time` only; 17 named scenarios (TC-01–TC-20)                                                            |
| Room ILP             | —                            | No automated unit tests in-repo; Gurobi code reviewed by ORIE expert (above) and exercised via pipeline + Sheets |


### Dependencies for running tests

- Python 3.x  
- `pandas`, `pytest` (and the same imports `find_slots` requires)

Gurobi is **not** required to run `test/test_resolve_slots.py`.

---

## Related documentation

- `docs/architecture.md` — system and MILP objective/constraints at a high level  
- `docs/workflow_analysis.md` — detailed variable and constraint mapping for the solver  
- `utils/gurobi_solver_summary.md` — narrative summary of an earlier formulation variant (use with `gurobi_solver.py` and architecture docs for the current picture)

---

## Limitations and follow-ups

1. **Add** small deterministic fixtures for `allot_rooms` (tiny `exams_df` / `rooms_df`) if fully automated regression testing for the ILP is required without a Gurobi license in CI.
2. **Track** assignment counts and unresolved reasons over time if you need quantitative semester-over-semester comparisons.

