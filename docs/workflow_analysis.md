# SDS-ATP Workflow Analysis

For a concise architecture view (components, diagrams, MILP design rationale), see **[architecture.md](architecture.md)**.

## Overview

SDS-ATP is a two-phase exam scheduling and room allocation system for students with special testing needs (accommodations). It reads data from Google Sheets, resolves time-slot conflicts, and assigns rooms using a Gurobi Integer Linear Programming (ILP) solver.

**Phase 1** — Resolve _when_ each exam happens (time slot assignment)
**Phase 2** — Resolve _where_ each exam happens (room assignment)

The pipeline is orchestrated by the `Prelims` class in `service/prelims.py`.

### Data Flow

```
Google Sheets (SP26 Input)          Local Files
       |                                |
       v                                v
 process_course_list()          get_timetables()
       |                          (student_timetable.json)
       v                                |
 get_valid_exams()                      |
       |                                |
       +----------+---------------------+
                  |
                  v
         resolve_time()          <-- Phase 1: Time slot resolution
                  |
                  v
            get_rooms()
                  |
                  v
          get_exams_df()
                  |
                  v
          allot_rooms()          <-- Phase 2: Gurobi room assignment
                  |
                  v
       Google Sheets (SP26 Output) + local CSVs
```

---

## Part 1: Pipeline Steps Before Gurobi

### Step 1: `process_course_list()` — Parse instructor conflict preferences

**Source:** `service/prelims.py` lines 21-36

**Input:** Google Sheet "SP26 Input" > "Courses Raw Form" — one row per course, containing a multi-select column where instructors indicate which alternative exam times they accept for students with conflicts.

**What it does:**

- Reads the multi-select column: _"If there is an academic conflict with a scheduled exam, the conflict exam options are..."_
- Explodes it into 10 binary (Y/N) columns, one per option:
  - "8:00 am the day of the exam" / "5:00 pm the day of the exam"
  - "8:00 am the day BEFORE the exam" / "5:00 pm the day BEFORE the exam"
  - "8:00 am the day AFTER the exam" / "5:00 pm the day AFTER the exam"
  - "8:00 am up to a week AFTER the exam" / "5:00 pm up to a week AFTER the exam"
  - "Conflict exams will be managed internally..."
  - "Other"

**Output:** DataFrame with columns: `[CRN, Class start timings, Class end timings, Days the class is offered, <10 binary preference columns>]`

**Why this step matters:** The time-slot resolver (Step 4) needs to know which alternative slots each instructor has approved. Without this, we wouldn't know where to reschedule a conflicting exam.

---

### Step 2: `get_valid_exams()` — Identify new exams to schedule

**Source:** `service/prelims.py` lines 38-65

**Input:**

- Google Sheet "SP26 Input" > "AIM Data" — exam records from the external AIM system
- Google Sheet "SP26 Output" > "SP26 Prelim" — our internal tracking sheet with previously processed exams

**What it does:**

1. **Syncs cancellations:** Any exam marked "Cancelled" in AIM gets its `Internal Status` and `Status` set to "Cancelled" in our internal sheet
2. **Filters to active exams:** Keeps only AIM exams with `Status == 'Active'`
3. **Identifies new exams:** Computes the set difference between AIM Exam_IDs and internal Exam_IDs to find exams we haven't processed yet
4. **Preserves original schedule:** Renames `Date`, `Time_Start`, `Time_End` to `Original Date`, `Original Time_Start`, `Original Time_End`
5. **Initializes scheduling columns:** Sets `Date`, `Time_Start`, `Time_End`, `Room No` to None and `Internal Status` to "Slot to be booked"
6. **Merges** new exams into the internal tracking sheet

**Output:** DataFrame of exams with `Internal Status == "Slot to be booked"` — only those that still need scheduling.

**Why this step matters:** Enables incremental processing. Each run only handles new/unprocessed exams rather than re-scheduling everything. Also ensures cancelled exams are properly tracked.

---

### Step 3: `get_timetables()` — Load student class schedules

**Source:** `service/prelims.py` lines 67-71

**Input:** `timetables/student_timetable.json` — JSON file containing each student's weekly class schedule.

**Data structure:**

```json
{
  "students": [
    {
      "student_id": "57740",
      "Timings": [
        {
          "Day": "Monday",
          "Slots": [
            { "start_time": "08:40", "end_time": "09:55" },
            { "start_time": "13:25", "end_time": "14:40" }
          ]
        }
      ]
    }
  ]
}
```

**Output:** In-memory dictionary used for conflict checking in Step 4.

**Why this step matters:** To avoid scheduling an exam during a student's other classes, we need their full weekly schedule.

---

### Step 4: `get_time_slots()` / `resolve_time()` — Core scheduling algorithm

**Source:** `service/prelims.py` lines 73-76 (orchestration), `utils/find_slots.py` lines 4-223 (algorithm)

**Input:** Course preferences (Step 1), exams to book (Step 2), student timetables (Step 3)

**Algorithm (per exam):**

1. **Try the original exam slot first:**
   - Check if the original time is free from conflicts using `slot_is_free_aware()`
   - This function checks against:
     - The student's class schedule (timetable) — avoids scheduling during other classes
     - Previously scheduled exams for this student — avoids double-booking
     - **Special "own class" rule:** If the exam falls during the student's own class for _this specific course_, it's allowed — _unless_ the exam duration bleeds past the class end time (accommodation students often have extended time)
   - Also checks tag constraints: NOAM (no exams before 9:00 AM) and NOPM (no exams ending after 6:00 PM)
   - If the original slot passes all checks, it's booked immediately

2. **If original slot fails, try alternatives in priority order:**
   The algorithm iterates through `CANDIDATE_RULES`:

   | Priority | Options                              | Day offset |
   | -------- | ------------------------------------ | ---------- |
   | 1st      | 8:00 AM / 5:00 PM day of exam        | 0          |
   | 2nd      | 8:00 AM / 5:00 PM day before         | -1         |
   | 3rd      | 8:00 AM / 5:00 PM day after          | +1         |
   | 4th      | 8:00 AM / 5:00 PM up to a week after | +2 to +7   |

   For each rule:
   - Only tries if the instructor marked it "Y" in their preferences
   - Prefers AM anchor (8:00) if AM is "Y", otherwise PM anchor (17:00)
   - NOAM tag bumps the 8:00 AM anchor to 9:00 AM
   - Validates against all class conflicts and previously scheduled exams
   - For "up to a week after," tries each day from +2 to +7, stopping at the first available

3. **If no slot found:** Sets `Internal Status = "Slot to be booked"` (remains unresolved)

**Key data tracking:** A `scheduled` dictionary tracks `{student_id: [(date, start, end), ...]}` to prevent scheduling overlapping exams for the same student.

**Output:** Updated exams DataFrame with `Date`, `Time_Start`, `Time_End` filled in and `Internal Status = "Slot booked"` for successfully scheduled exams. Saved to `result1.csv` and synced back to Google Sheets.

---

### Step 5: `get_rooms()` — Build room availability table

**Source:** `service/prelims.py` lines 78-85

**Input:**

- Google Sheet "SP26 Input" > "LIV25" — master room list with capacity, zone, and flags
- Google Sheet "SP26 Input" > "Room Availability" — which rooms are available on which dates/times

**What it does:**

1. Filters LIV25 to rooms where `S25 == "Y"` (available this semester) AND `AIM == "Y"` (approved for AIM testing)
2. Selects `[Location_Name, Testing capacity, Zone]`
3. Left-joins Room Availability with the filtered room list on `Location_Name`

**Output:** `rooms.csv` — merged **Room Availability** rows plus `Testing capacity` and `Zone` from LIV25 (column set follows the availability sheet, including identifiers such as `slot_id` when present).

Example (illustrative):

```
slot_id,Location_Name,Date,Time_Start,Time_End,Testing capacity,Zone
s0001,ADW109,12/15/2024,800,1200,14,1
s0002,ADW109,12/15/2024,1300,1900,14,1
s0022,ASA109,12/15/2024,800,2200,40,2
```

---

### Step 6: `get_exams_df()` — Filter to successfully scheduled exams

**Source:** `service/prelims.py` lines 87-91

**Input:** Google Sheet "SP26 Output" > "SP26 Prelim" (after time resolution)

**What it does:** Filters to only exams with `Internal Status == "Slot booked"` — those that were successfully assigned a time slot and are now ready for room assignment.

**Output:** `exams.csv` with columns: `[Exam_ID, Student_ID, Course_ID, Original Date, Original Time_Start, Original Time_End, Date, Time_Start, Time_End, Multiplier, Status, Tags, Room No, Internal Status]`

Example:

```
Exam_ID,Student_ID,Course_ID,...,Date,Time_Start,Time_End,...,Tags,...
68680,57740,10001,...,12/15/2024,840,1037,...,ACDF|COMP|RD,...
68283,57741,10002,...,12/16/2024,800,1010,...,PRIV,...
```

---

### Summary: What enters the Gurobi solver

| Dataset     | Records               | Key columns                                                       |
| ----------- | --------------------- | ----------------------------------------------------------------- |
| `exams.csv` | ~30 exams (mock data) | Exam_ID, Student_ID, Course_ID, Date, Time_Start, Time_End, Tags  |
| `rooms.csv` | ~51 room-slots        | slot_id (if present), Location_Name, Date, Time_Start, Time_End, Testing capacity, Zone |

The solver's job: assign each exam to **at most one** room availability row (`j`) such that the exam fits the row’s date/time window and **15-minute** room pre-buffer; then pack exams into **concurrent groups** (same `Time_Start` within `j`) under capacity and course limits, enforce **RD** / **PRIV**/**CODS** rules per group, and forbid gaps **under 15 minutes** between **non-concurrent** exams in the same slot (with a soft preference toward **30+** minute gaps).

---

## Part 2: Gurobi Solver Analysis

**Source:** `utils/gurobi_solver.py`

### Concurrent exam-groups

Within each room slot row `j` (one availability window), exams are grouped by **exact** start time `Time_Start` (in minutes). Capacity, the “max 3 courses” rule, RD limits, and PRIV/CODS isolation apply **per concurrent group** `(j, ts)`, not necessarily across the entire row. Multiple non-overlapping sessions can share one slot row if **inter-exam gaps** satisfy C7.

### Decision Variables

| Variable | Type | Meaning |
| -------- | ---- | ------- |
| `x[i,j]` | Binary | 1 if exam `i` uses room slot `j`. |
| `y[j]` | Binary | 1 if slot `j` has at least one exam. |
| `z_g[c,j,ts]` | Binary | 1 if course `c` appears in slot `j` in the concurrent group that starts at `ts`. |
| `rd_flag_g[j,ts]` | Binary | 1 if any RD-tagged exam is in group `(j,ts)`. |
| `q[i1,i2,j]` | Binary | Linked so that `q=1` when both exams are in `j` with a **15–29 minute** gap between their windows (used in the P2 objective). |

### Compatibility Pre-computation

An exam `i` is compatible with slot `j` if and only if:

- Same `Date`
- Exam interval inside the room row window
- **≥ 15 minutes** between room open and exam start (`_hhmm_to_minutes`)

Optional quality flags:

- `has_30_buffer`: ≥ 30 minutes pre-open
- `has_15_post_buffer`: ≥ 15 minutes after exam end before room close

Only compatible pairs receive an `x[i,j]` variable (sparse model).

### Objective Hierarchy

Gurobi `setObjectiveN` (all minimization; higher priority index solved first):

| Priority | Name | Description |
| -------- | ---- | ----------- |
| **P5** | `max_assign` | `minimize -sum(x[i,j])` — maximize assigned exams. |
| **P4** | `min_rooms` | `minimize sum(y[j])` — minimize distinct slot rows used. |
| **P3** | `min_rooms_per_course` | `minimize sum(z_g[...])` — **spread each course across fewer** `(room, start-time)` groups (administrative clustering). |
| **P2** | `prefer_30_buffer` | Penalize room opens with only **15–29 min** pre-buffer (`only_15`) **and** penalize inter-exam pairs in `inter_only_15` via `sum(q)`. |
| **P1** | `prefer_15_post` | Penalize assignments missing **≥15 min** post-exam buffer before room close. |
| **P0** | `prefer_zone1` | Penalize Zone-2 assignments (lowest priority). |

### Constraints

#### C1 — Single Assignment

For each exam `i`: `sum_j x[i,j] <= 1` over compatible `j`.

#### C2 — Capacity per concurrent group

For each `(j, ts)` group: `sum_{i in group(j,ts)} x[i,j] <= Testing capacity`.

#### C3 — At most 3 courses per concurrent group

Uses `z_g[c,j,ts]` with standard linking (`z_g >= x` for exams of course `c` in that group, `z_g <= sum x` upper bound) and `sum_c z_g[c,j,ts] <= 3`.

**Rationale:** Limits proctoring load for **simultaneous** exams in the same room window.

#### C4 — RD tag within a concurrent group

For each `(j, ts)` with physical cap > 20: if any RD exam is in the group, the group's headcount is capped at **20** (same big-M pattern as before, but scoped to `(j,ts)` via `rd_flag_g`).

#### C5 — PRIV / CODS within a concurrent group

For a PRIV/CODS exam `i` at start time `ts` in slot `j`, no other exam with the **same** `(j, ts)` may be assigned. Other **different** start times in the same slot row may still be used if C7 gap rules allow.

#### C6 — Room pre-buffer (compatibility + objective)

Hard **15-minute** minimum is enforced in compatibility; **30-minute** pre-open is preferred via the P2 term on `only_15`.

#### C7 — Inter-exam spacing in the same slot row

For each pair of exams that could both go to slot `j` with **non-concurrent** windows:

- If the gap between windows is **under 15 minutes**, `x[i1,j] + x[i2,j] <= 1` (**hard**).
- If the gap is **15–29 minutes**, both may be assigned, but `q[i1,i2,j]` is forced on when both are assigned and contributes to **P2** so the solver prefers **30+** minute spacing when trade-offs exist.

**Rationale:** Staggered sessions in one booked block need explicit turnover time; concurrent exams (identical start) are exempt from inter-exam gap rules.

### Solver Output

After optimization, the solver:

1. Sets `Room No` to `Location_Name` for assigned rows.
2. Sets `Internal Status = "Room allocated"` for assigned exams.
3. Prints counts and a per-slot summary (includes `slot_id` when present in `rooms_df`).
4. Lists unassigned exams.

---

## Part 3: Edge Cases and Mock Data for Testing

### Edge Cases to Consider

#### Time Slot Resolution (`find_slots.py`)

| #   | Edge Case                                       | Risk                                                                                        | Current Behavior                                                                                                   |
| --- | ----------------------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 1   | **Student with many exams on consecutive days** | Each scheduled exam constrains the next; processing order matters                           | Exams processed in DataFrame row order; first exam gets priority                                                   |
| 2   | **Multiplier and duration**                     | The `Multiplier` column exists but `resolve_time()` uses `Original Time_Start/End` directly | The original times already account for extended duration (pre-computed). Verify this assumption holds for all data |
| 3   | **Weekend scheduling**                          | Alternative slots can land on Saturday/Sunday                                               | No class conflicts on weekends (good), but verify rooms are actually available on those dates                      |
| 4   | **All instructor preferences "N"**              | No alternative options to try                                                               | Exam stays as "Slot to be booked" (unresolved) — requires manual intervention                                      |
| 5   | **NOAM + NOPM combined**                        | Valid window is only 9:00-18:00                                                             | Works for short exams; long exams (3+ hours starting at 5 PM) would fail NOPM                                      |
| 6   | **Processing order dependency**                 | Student A's first exam gets preferred slot, second may get worse slot                       | Inherent to sequential algorithm; could be improved with global optimization but adds complexity                   |

#### Gurobi Solver (`gurobi_solver.py`)

| #   | Edge Case                                             | Risk                                   | Current Behavior                                                              |
| --- | ----------------------------------------------------- | -------------------------------------- | ----------------------------------------------------------------------------- |
| 7   | **More PRIV/CODS students than available solo concurrent groups** | Not enough room rows / groups for all private exams | Some PRIV exams go unassigned; **P5** objective still maximizes total assignments first |
| 8   | **RD student in large room (cap > 20)**               | Concurrent group capped at 20 when RD present | By design — scoped to the **(room slot, start time)** group |
| 9   | **More than 3 courses at the same start time**        | Spillover to additional rooms or slots needed | C3 applies **per (j, ts)** concurrent group |
| 10  | **All rooms full on a given date**                    | Some exams unassigned                  | Solver returns partial assignment; unassigned exams reported                  |
| 11  | **Staggered exams in one long slot row**              | Tight back-to-back windows             | **Under 15 min** gap blocks both; **15–29 min** allowed but penalized in **P2** toward **30+ min** gaps |
| 12  | **Only Zone-2 rooms available**                       | Solver should still assign             | Yes — Zone preference is **P0** (lowest priority), won't block assignments        |

#### Data Integrity

| #   | Edge Case                        | Risk                                            | Current Behavior                                        |
| --- | -------------------------------- | ----------------------------------------------- | ------------------------------------------------------- |
| 13  | **Mismatched CRN**               | Exam's Course_ID not in course preference table | `resolve_time()` sets "Unresolved - no course pref"     |
| 14  | **Student not in timetable**     | No class schedule to check                      | Treated as no conflicts — all slots are free            |
| 15  | **Room with capacity 0 or null** | Would break solver                              | Already handled — solver drops these rows (see `gurobi_solver.py` after loading rooms) |

### Known Bug

**Status string mismatch between tests and code:**

- Test file (`test/test_resolve_slots.py`) TC-06, TC-12, TC-20 expect `"Unresolved - no available slot"`
- But `find_slots.py` line 221 sets unbooked exams to `"Slot to be booked"`
- These tests would currently fail. The status string in code should likely be updated to `"Unresolved - no available slot"` to distinguish between "hasn't been processed yet" and "was processed but no slot could be found."

### Suggested Mock Data Test Scenarios

#### For the Gurobi solver (create small CSVs matching `exams.csv` / `rooms.csv` format):

| Scenario                   | Exams Setup                                    | Rooms Setup                                   | Expected Result                                             |
| -------------------------- | ---------------------------------------------- | --------------------------------------------- | ----------------------------------------------------------- |
| **Basic happy path**       | 5 exams, no special tags, different courses    | 2 rooms with capacity 10 each                 | All 5 assigned, Zone-1 preferred                            |
| **PRIV saturation**        | 3 PRIV students, **same** date/time (same concurrent group) | 2 small rooms (cap 8 each)                    | At most 2 concurrent groups can be solo; 1 unassigned |
| **RD capacity squeeze**    | 25 students (1 with RD tag), **same** start time in one slot | 1 room row with cap=30                        | That concurrent group capped at 20; 5 unassigned |
| **3-course limit**         | 4 students from 4 different courses, **same** start time   | 1 room row with cap=10                        | Only 3 courses fit in the group; 4th needs another row or time |
| **Zone preference**        | 5 exams, same time                             | 1 Zone-1 room (cap=3) + 1 Zone-2 room (cap=3) | Zone-1 fills first (3 students), Zone-2 gets remaining 2    |
| **Inter-exam gap**         | Two exams, same slot row, **non-concurrent** windows with 10 min gap | 1 room row covering both                    | At most one of the two can be assigned (hard **under 15 min** rule) |
| **No compatible rooms**    | Exams on 12/25/2024                            | No rooms available 12/25                      | All unassigned, solver returns gracefully                   |
| **Mixed tags**             | 1 PRIV + 1 RD + 3 regular, **same** start time | 3 room rows (cap 8, 25, 10)                   | PRIV alone in its concurrent group; RD caps that group to 20 in a large-cap row |

#### For the time slot resolver (use existing test helpers in `test/test_resolve_slots.py`):

| Scenario               | Setup                                                       | Expected Result                                                          |
| ---------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------ |
| **3 exams cascading**  | Student with 3 exams all originally at 10:00 AM on same day | First keeps original, second/third rescheduled to different alternatives |
| **NOAM + long exam**   | NOAM tag, 4-hour exam, 5 PM preference                      | Starts at 5 PM, ends 9 PM — should this violate anything?                |
| **Weekend fallback**   | Original on Friday conflicts, "day after" = Saturday        | Books Saturday; verify room availability matches                         |
| **No timetable entry** | Student not in JSON at all                                  | All slots considered free; original slot booked                          |

#### How to create mock data

**For `resolve_time()` tests:** Use existing helpers in `test/test_resolve_slots.py`:

```python
pref = make_pref(crn=101, class_start="08:00", class_end="09:00", days="M", am_exam="Y")
exam = make_exam(student_id=1, exam_id=1, crn=101, orig_date="04/07/2025", orig_start=1000, orig_end=1100)
tt = make_timetable(student_id=1, day_slots={"Monday": [("08:00", "09:00")]})
result = resolve_time(pref, exam, tt)
```

**For `allot_rooms()` tests:** Create DataFrames matching the CSV column structure and call `allot_rooms()` directly — no Google Sheets dependency:

```python
import pandas as pd
from utils.gurobi_solver import allot_rooms

exams_df = pd.DataFrame([
    {"Exam_ID": "E1", "Student_ID": "S1", "Course_ID": "C1",
     "Date": "12/15/2024", "Time_Start": 900, "Time_End": 1100,
     "Tags": "RD", "Room No": None, "Internal Status": "Slot booked"}
])

rooms_df = pd.DataFrame([
    {"slot_id": "s0001", "Location_Name": "ROOM_A", "Date": "12/15/2024",
     "Time_Start": 800, "Time_End": 1200,
     "Testing capacity": 30, "Zone": 1}
])

result = allot_rooms(exams_df, rooms_df)
```

---

## Appendix: Tag Reference

| Tag      | Full Name                | Time Slot Effect                 | Room Effect                   |
| -------- | ------------------------ | -------------------------------- | ----------------------------- |
| **NOAM** | No Morning               | Exam cannot start before 9:00 AM | None                          |
| **NOPM** | No PM/Evening            | Exam cannot end after 6:00 PM    | None                          |
| **RD**   | Reader/Disability        | None                             | Concurrent group capped at 20 students when room cap > 20 |
| **PRIV** | Private                  | None                             | Must be **alone in the concurrent exam-group** (same room slot + start time) |
| **CODS** | Code Switch              | None                             | Same as PRIV for room grouping |
| **ACDF** | Academic Disability Flag | Tracking only                    | None                          |
| **COMP** | Component-based          | Tracking only                    | None                          |

## Appendix: Internal Status Lifecycle

```
"Slot to be booked"  -->  resolve_time()  -->  "Slot booked"
                                           -->  "Unresolved - no course pref" (no CRN match)
                                           -->  "Slot to be booked" (no slot found*)

"Slot booked"        -->  allot_rooms()   -->  "Room allocated"
                                           -->  (unchanged if unassigned)

"Room allocated"     -->  (manual)        -->  "Completed"

"Cancelled"          -->  (terminal state)
```

\*Note: Code currently reuses "Slot to be booked" for unresolved exams. Tests expect "Unresolved - no available slot" — see Known Bug section.
