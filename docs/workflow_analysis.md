# SDS-ATP Workflow Analysis

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

**Output:** `rooms.csv` with columns: `[slot_id, Location_Name, Date, Time_Start, Time_End, Max_Cap, Zone]`

Example:

```
slot_id,Location_Name,Date,Time_Start,Time_End,Max_Cap,Zone
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
| `rooms.csv` | ~51 room-slots        | slot_id, Location_Name, Date, Time_Start, Time_End, Max_Cap, Zone |

The solver's job: assign each exam to a room slot such that the exam's scheduled time fits within the room's available window, while respecting capacity, tag-based accommodations, and course diversity constraints.

---

## Part 2: Gurobi Solver Analysis

**Source:** `utils/gurobi_solver.py`

### Decision Variables

| Variable     | Type   | Meaning                                            |
| ------------ | ------ | -------------------------------------------------- |
| `x[i,j]`     | Binary | 1 if exam `i` is assigned to room slot `j`         |
| `y[j]`       | Binary | 1 if room slot `j` is used (has at least one exam) |
| `z[c,j]`     | Binary | 1 if course `c` has any exam in room slot `j`      |
| `rd_flag[j]` | Binary | 1 if any RD-tagged student is in room slot `j`     |

### Compatibility Pre-computation

Before building the model, the solver pre-computes which (exam, room) pairs are compatible. An exam `i` is compatible with room slot `j` if and only if:

- Same date: `exam.Date == room.Date`
- Exam fits within room window: `exam.Time_Start >= room.Time_Start AND exam.Time_End <= room.Time_End`

This creates a sparse set of valid assignment pairs, reducing the number of variables and constraints.

### Objective Hierarchy

The solver uses Gurobi's multi-objective capability with three prioritized objectives (all formulated as minimization):

| Priority         | Objective                        | Formula                                  |
| ---------------- | -------------------------------- | ---------------------------------------- |
| **P3 (highest)** | Maximize exam assignments        | `minimize -sum(x[i,j])`                  |
| **P2**           | Minimize rooms used              | `minimize sum(y[j])`                     |
| **P1**           | Prefer 30-minute pre-exam buffer | `minimize sum(x[i, j]) in only_15`       |
| **P0 (lowest)**  | Prefer Zone-1 (nearby)           | `minimize sum(x[i,j] where j in Zone-2)` |

**How this hierarchy works:** Gurobi solves objectives in priority order. It first finds the maximum number of assignable exams. Among all solutions achieving that maximum, it picks the one using the fewest rooms. Among those, it prefers assignments where the room opens at least 30 minutes before the exam (rather than the hard-minimum 15 minutes). Finally, among those, it minimizes Zone-2 usage.

### Constraints

#### C1 — Single Assignment

```
For each exam i: sum(x[i,j] for j in compatible_rooms[i]) <= 1
```

Each exam is assigned to **at most one** room slot. (Not "exactly one" — some exams may be unassignable if rooms are full.)

#### C2 — Room Capacity

```
For each room j: sum(x[i,j] for i in compatible_exams[j]) <= capacity[j]
```

The number of students assigned to a room slot cannot exceed its testing capacity.

#### C3 — Course Diversity (max 3 courses per room)

Uses auxiliary `z[c,j]` variables to track which courses are present in each room:

- Linking: `z[c,j] >= x[i,j]` for each exam `i` of course `c` (if any exam of course `c` is in room `j`, the indicator is forced to 1)
- Upper bound: `z[c,j] <= sum(x[i,j] for i in course_exams[c])` (indicator is 0 if no exams of course `c` are assigned)
- Enforcement: `sum(z[c,j] for all courses c) <= 3`

**Rationale:** Limits proctoring complexity. Having more than 3 different exams in one room makes administration difficult.

#### C4 — RD Tag Capacity Reduction

```
For each room j with cap > 20:
  rd_flag[j] >= x[i,j]  for each RD-tagged exam i
  sum(x[i,j]) <= cap - (cap - 20) * rd_flag[j]
```

If **any** student with the RD (Reader/Disability) tag is placed in a room, that room's effective capacity drops to 20, regardless of its physical capacity. This uses a big-M linearization: when `rd_flag[j] = 1`, the right-hand side becomes `cap - cap + 20 = 20`.

**Rationale:** RD students require a quieter, less crowded environment for their reader accommodations.

#### C5 — Privacy (PRIV / CODS tags)

```
For each PRIV/CODS exam i and compatible room j:
  sum(x[k,j] for k != i) <= cap * (1 - x[i,j])
```

If a PRIV or CODS student is assigned to room `j` (`x[i,j] = 1`), then all other assignments to that room are forced to 0. The student takes the exam **alone** in the room.

**Rationale:** These students require a private testing environment due to their accommodations (e.g., reading aloud, dictation software).

#### C6 — Overlapping Time Slots (shared capacity)

```
For overlapping slots j1, j2 in the same physical room on the same date:
  sum(x[i,j] for i,j in both slots) <= capacity
```

If a physical room has two time slots that overlap (e.g., 8:00-12:00 and 10:00-14:00), they share a single capacity limit. This prevents over-filling the physical space.

#### C7 — Pre-Exam Buffer (15-minute hard minimum, 30-minute soft preference)

C7 is enforced in two layers — a **hard constraint** baked into the compatibility pre-computation and a **soft preference** in the objective hierarchy.

**Hard constraint (15-minute minimum):**
During compatibility pre-computation, an exam `i` is only considered compatible with room slot `j` if the room opens at least 15 minutes before the exam starts. Time values are converted from HHMM format to minutes since midnight using `_hhmm_to_minutes()` for accurate arithmetic:

```
Compatible if:
  exam.Date == room.Date
  AND  _hhmm_to_minutes(exam.Time_Start) - 15 >= _hhmm_to_minutes(room.Time_Start)
  AND  _hhmm_to_minutes(exam.Time_End)         <= _hhmm_to_minutes(room.Time_End)
```

Any (exam, room) pair that doesn't meet the 15-minute buffer is excluded entirely — the solver cannot assign an exam to that room slot regardless of other constraints.

**Soft preference (30-minute buffer):**
Among compatible pairs, the solver further tracks which pairs have a full 30-minute buffer (`has_30_buffer` set). Pairs that are compatible but only have a 15–29 minute buffer land in the `only_15` set (`compat - has_30_buffer`). The P1 objective minimizes assignments in `only_15`, steering the solver toward rooms that open 30+ minutes early whenever possible — without sacrificing assignment count or room efficiency.

**Rationale:** Proctors need setup time before students arrive. 15 minutes is the operational minimum; 30 minutes is preferred to allow for room arrangement, material distribution, and technology checks.

### Solver Output

After optimization, the solver:

1. Updates `Room No` with the assigned room's `Location_Name`
2. Sets `Internal Status = "Room allocated"` for assigned exams
3. Prints a summary: exams assigned, rooms used, per-room breakdown (students, courses)
4. Lists any unassigned exams

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
| 7   | **More PRIV/CODS students than available solo rooms** | Not enough rooms for all private exams | Some PRIV exams go unassigned; P2 objective still maximizes total assignments |
| 8   | **RD student in large room (cap > 20)**               | Capacity drops to 20, wasting space    | By design — RD accommodation takes priority over space efficiency             |
| 9   | **More than 3 courses in same time window**           | Spillover to additional rooms needed   | C3 constraint forces the 4th+ course into separate rooms                      |
| 10  | **All rooms full on a given date**                    | Some exams unassigned                  | Solver returns partial assignment; unassigned exams reported                  |
| 11  | **Overlapping room slots (C6)**                       | Shared capacity could be confusing     | Correctly implemented — uses pairwise overlap detection                       |
| 12  | **Only Zone-2 rooms available**                       | Solver should still assign             | Yes — Zone preference is P0 (lowest priority), won't block assignments        |

#### Data Integrity

| #   | Edge Case                        | Risk                                            | Current Behavior                                        |
| --- | -------------------------------- | ----------------------------------------------- | ------------------------------------------------------- |
| 13  | **Mismatched CRN**               | Exam's Course_ID not in course preference table | `resolve_time()` sets "Unresolved - no course pref"     |
| 14  | **Student not in timetable**     | No class schedule to check                      | Treated as no conflicts — all slots are free            |
| 15  | **Room with capacity 0 or null** | Would break solver                              | Already handled — solver drops these rows (lines 33-34) |

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
| **PRIV saturation**        | 3 PRIV students, same date/time                | 2 small rooms (cap 8 each)                    | Only 2 assigned (each alone); 1 unassigned                  |
| **RD capacity squeeze**    | 25 students (1 with RD tag), same time         | 1 room with cap=30                            | Room capped at 20; 5 students unassigned                    |
| **3-course limit**         | 4 students from 4 different courses, same time | 1 room with cap=10                            | Only 3 courses fit; 4th needs another room or is unassigned |
| **Zone preference**        | 5 exams, same time                             | 1 Zone-1 room (cap=3) + 1 Zone-2 room (cap=3) | Zone-1 fills first (3 students), Zone-2 gets remaining 2    |
| **Overlapping room slots** | 8 exams across two overlapping time windows    | 1 room with 2 overlapping slots (cap=5)       | Shared capacity = 5 total, not 5+5                          |
| **No compatible rooms**    | Exams on 12/25/2024                            | No rooms available 12/25                      | All unassigned, solver returns gracefully                   |
| **Mixed tags**             | 1 PRIV + 1 RD + 3 regular, same time           | 3 rooms (cap 8, 25, 10)                       | PRIV gets solo room; RD caps the 25-cap room to 20          |

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
    {"Location_Name": "ROOM_A", "Date": "12/15/2024",
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
| **RD**   | Reader/Disability        | None                             | Room capped at 20 students    |
| **PRIV** | Private                  | None                             | Student must be alone in room |
| **CODS** | Code Switch              | None                             | Student must be alone in room |
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
