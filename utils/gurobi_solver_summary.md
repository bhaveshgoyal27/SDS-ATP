# `gurobi_solver.py` — Room Allocation via Integer Linear Programming

## Overview

This module assigns exam students to available room slots using a **Gurobi Integer Linear Program (ILP)**. It takes in two DataFrames — one describing exams and one describing rooms — and returns an updated exams DataFrame with room assignments filled in.

---

## Inputs

### `exams_df` — Exam DataFrame

Each row represents a single student sitting a single exam. Expected columns:

| Column | Description |
|---|---|
| `Exam_ID` | Unique identifier for the exam |
| `Student_ID` | Unique identifier for the student |
| `Course_ID` | Course the exam belongs to |
| `Date` | Exam date (string) |
| `Time_Start` | Start time in HHMM format (e.g. `930` = 09:30) |
| `Time_End` | End time in HHMM format |
| `Tags` | Pipe-delimited accommodation tags (e.g. `"RD"`, `"PRIV\|CODS"`) |
| `Room No` | Initially empty; populated by the solver |
| `Internal Status` | Initially empty; set to `"Room allocated"` on success |

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

---

## What the Solver Does

### 1. Data Preparation

- Drops rooms with missing or zero capacity.
- Parses student accommodation tags (`RD`, `PRIV`, `CODS`) from the pipe-delimited `Tags` field.

### 2. Compatibility Pre-computation

For every (exam, room) pair the solver checks whether the room slot's window covers the exam time with at least a **15-minute pre-exam buffer** (hard requirement). It also records whether a **30-minute pre-exam** or **15-minute post-exam** buffer exists (soft preferences).

### 3. ILP Formulation

**Decision variables:**

| Variable | Type | Meaning |
|---|---|---|
| `x[i, j]` | Binary | 1 if exam-row `i` is assigned to room slot `j` |
| `y[j]` | Binary | 1 if room slot `j` is used at all |
| `z[c, j]` | Binary | 1 if course `c` has any student in room `j` |
| `rd_flag[j]` | Binary | 1 if any RD-tagged student is in room `j` |

**Constraints:**

| ID | Rule |
|---|---|
| C1 | Each exam-row is assigned to **at most one** room slot. |
| C2 | Total students in a room slot cannot exceed its **testing capacity**. |
| C3 | At most **3 distinct courses** per room slot. |
| C4 | If any student in a room carries the **RD** tag, the room is capped at **20 students**. |
| C5 | Students with **PRIV** or **CODS** tags must be **alone** in their room. |
| C6 | Overlapping time-slots for the **same physical room on the same date** share a single capacity limit. |
| C7 | Room must open at least **15 minutes** before the exam starts (enforced during compatibility). |

**Multi-objective hierarchy (highest priority first):**

| Priority | Objective |
|---|---|
| P4 | **Maximise** the number of exams assigned. |
| P3 | **Minimise** the number of room slots used. |
| P2 | **Prefer** a 30-minute pre-exam buffer over 15-minute. |
| P1 | **Prefer** rooms with a 15-minute post-exam buffer. |
| P0 | **Prefer** Zone-1 rooms over Zone-2. |

### 4. Solve & Report

Gurobi solves the model and the function prints a summary: how many exams were assigned, how many rooms were used, and per-room details including student and course counts. Any unassigned exams are listed separately.

---

## Output

Returns the **`exams` DataFrame** (a copy of `exams_df`) with two columns updated for every successfully assigned row:

| Column | Value |
|---|---|
| `Room No` | The `Location_Name` of the assigned room slot |
| `Internal Status` | `"Room allocated"` |

Rows that could not be assigned remain unchanged.
