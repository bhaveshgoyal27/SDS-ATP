# `gurobi_solver_grouped.py` — Cohort-Aware Room Allocation via ILP

## Overview

This module assigns exam students to available room slots using a **Gurobi Integer Linear Program (ILP)**, with students grouped into **exam cohorts**. It is the room-allocation backend used by `service/prelims.py` (imported as `solve_rooms`).

Compared with `gurobi_solver.py`:

- Students sharing the same `(Course_ID, Date, Time_Start, Time_End)` form one **exam cohort**.
- The solver prefers keeping each cohort in as few rooms as possible (ideally one); it only splits a cohort when capacity, tags, or course-mix rules require it.
- After assignment, it also builds a **bookings** DataFrame with room reservation windows that include pre-/post-exam buffers.

It takes two DataFrames (exams and rooms) and returns `(exams_df, bookings_df)`.

---

## Inputs

### `exams_df` — Exam DataFrame

Each row represents a single student sitting a single exam. Expected columns:

| Column | Description |
|---|---|
| `Exam_ID` | Unique identifier for the exam request |
| `Student_ID` | Unique identifier for the student |
| `Course_ID` | Course the exam belongs to |
| `Date` | Booked exam date (string) |
| `Time_Start` | Booked start time in HHMM format (e.g. `930` = 09:30) |
| `Time_End` | Booked end time in HHMM format |
| `Tags` | Pipe-delimited accommodation tags (e.g. `"RD"`, `"PRIV\|CODS"`) |
| `Room No` | Initially empty; populated by the solver |
| `Internal Status` | Typically `"Slot booked"` on input; set to `"Room allocated"` on success |

### `rooms_df` — Room DataFrame

Each row represents a bookable room time-slot. Expected columns:

| Column | Description |
|---|---|
| `Location_Name` | Physical room name |
| `Date` | Date the slot is available (string) |
| `Time_Start` | Slot opening time in HHMM format |
| `Time_End` | Slot closing time in HHMM format |
| `Testing capacity` | Maximum number of students the slot can hold |
| `Zone` | Zone identifier (`1` preferred over `2`) |
| `slot_id` | Slot identifier (used in solve logs when present) |

---

## What the Solver Does

### 1. Data Preparation

- Drops rooms with missing or zero testing capacity.
- Normalizes dates and numeric times on both exams and rooms.
- Parses accommodation tags (`RD`, `PRIV`, `CODS`) from the pipe-delimited `Tags` field.

### 2. Exam Cohorts

Students are grouped by:

```text
(Course_ID, Date, Time_Start, Time_End)
```

All students in a cohort are taking the same course at the same booked sitting. PRIV / CODS students remain members of their cohort for the **per-exam room-count** objective, but still must sit alone in their concurrent room group (constraint C5).

### 3. Compatibility Pre-computation

For every (student exam-row, room slot) pair the solver checks whether:

- Dates match,
- The exam interval fits inside the room window, and
- The room opens at least **15 minutes** before exam start (hard requirement).

It also records soft buffer quality:

- **30-minute pre-exam** buffer available,
- **15-minute post-exam** buffer available (room still open after exam end).

### 4. Concurrent Groups & Inter-Exam Gaps

Within each room slot, candidate exams are partitioned by exact start time into **concurrent groups**. Capacity, course-mix, RD, and PRIV/CODS rules apply per concurrent group.

For non-concurrent pairs in the same slot:

- Gap **&lt; 15 minutes** → hard conflict (cannot both be assigned there),
- Gap **15–29 minutes** → allowed but penalized toward a **30+ minute** gap.

### 5. ILP Formulation

**Decision variables:**

| Variable | Type | Meaning |
|---|---|---|
| `x[i, j]` | Binary | 1 if student exam-row `i` is assigned to room slot `j` |
| `y[j]` | Binary | 1 if room slot `j` is used at all |
| `u[g, j]` | Binary | 1 if exam cohort `g` places at least one student in room `j` |
| `z_g[c, j, ts]` | Binary | 1 if course `c` appears in concurrent group `(j, ts)` |
| `rd_flag_g[j, ts]` | Binary | 1 if any RD-tagged student is in concurrent group `(j, ts)` |
| `q[i1, i2, j]` | Binary | 1 if both exams are in slot `j` with only a 15–29 minute gap |

**Constraints:**

| ID | Rule |
|---|---|
| C1 | Each student exam-row is assigned to **at most one** room slot. |
| C2 | Concurrent group size cannot exceed the room’s **testing capacity**. |
| C3 | At most **3 distinct courses** per concurrent group. |
| C4 | If any RD student is in a concurrent group and capacity &gt; 20, that group is capped at **20 students**. |
| C5 | `PRIV` / `CODS` students must be **alone** in their concurrent group. |
| C6 | Room must open ≥ **15 minutes** before exam start (compatibility filter). |
| C7 | Non-concurrent exams in the same slot need ≥ **15 minutes** between them (hard); 30 minutes preferred via P2. |
| — | `u[g, j]` is linked to `x` so it counts rooms used by each cohort. |
| — | `y[j]` is linked to `x` so it flags rooms that are used overall. |

**Multi-objective hierarchy (highest priority first):**

| Priority | Name | Objective |
|---|---|---|
| P5 | `max_assign` | **Maximise** the number of exams assigned. |
| P4 | `min_rooms_per_exam` | **Minimise** rooms used **per exam cohort** (avoid splitting). |
| P3 | `min_rooms_overall` | **Minimise** the total number of room slots used. |
| P2 | `prefer_30_buffer` | Prefer **30-minute** pre-exam / inter-exam buffers over 15-minute. |
| P1 | `prefer_15_post` | Prefer rooms with a **15-minute** post-exam buffer. |
| P0 | `prefer_zone1` | Prefer Zone-1 rooms over Zone-2. |

P4 is the main behavioral difference from `gurobi_solver.py`: keeping a cohort intact outranks shrinking the global room footprint.

### 6. Solve & Report

Gurobi solves the model lexicographically under the priorities above. The function prints:

- Number of exam cohorts, how many stayed in one room vs. were split,
- Exams assigned vs. total, rooms used, and distinct bookings,
- Per-used-slot details (students and courses),
- Any unassigned exams.

---

## Outputs

`allot_rooms(exams_df, rooms_df)` returns a **tuple** `(exams, bookings)`.

### 1. `exams` — Updated exam rows

A copy of `exams_df` with two columns updated for every successfully assigned row:

| Column | Value |
|---|---|
| `Room No` | The `Location_Name` of the assigned room slot |
| `Internal Status` | `"Room allocated"` |

**Exam `Time_Start` / `Time_End` are unchanged** — they stay as the original booked sitting. Buffers are not written into these columns. Unassigned rows remain unchanged.

### 2. `bookings` — Room reservations with buffers

One row per **distinct** room reservation after buffers are applied:

| Column | Description |
|---|---|
| `Date` | Exam / booking date |
| `Room No` | Assigned `Location_Name` |
| `Time_Start` | Buffered start (HHMM): exam start − **30** if the chosen slot supports a 30-min pre-buffer, else − **15** |
| `Time_End` | Buffered end (HHMM): exam end + **15** if the chosen slot supports a 15-min post-buffer, else + **0** |

Duplicate identical `(Date, Room No, Time_Start, Time_End)` rows are collapsed. Example: exam `0900–1100` on a 30/15-capable slot → booking `0830–1115`.

---

## Integration with `prelims.py`

`Prelims.allot_rooms` calls this solver as:

```python
from utils.gurobi_solver_grouped import allot_rooms as solve_rooms

result_df, bookings_df = solve_rooms(exams_df, rooms_df)
```

It writes:

- `result.csv` — updated exams (merged into Google Sheet **SP26 Output / SP26 Prelim** on `Exam_ID`),
- `room_bookings.csv` — buffered room reservation table.

---

## How This Differs from `gurobi_solver.py`

| Aspect | `gurobi_solver.py` | `gurobi_solver_grouped.py` |
|---|---|---|
| Student modeling | Each row optimized independently | Rows grouped into exam cohorts |
| Priority after max-assign | Minimise total rooms, then concentrate courses | Minimise **rooms per cohort**, then total rooms |
| Return value | `exams` only | `(exams, bookings)` |
| Buffered booking window | Not produced | Produced in `bookings` |
| Hard operational rules | Capacity, 3-course, RD, PRIV/CODS, buffers/gaps | Same |
