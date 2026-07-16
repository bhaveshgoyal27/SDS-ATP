# SDS-ATP Exam Scheduling — User Guide

This guide is for SDS-ATP staff who will run the exam scheduling pipeline as part of their semester workflow. It assumes clients have the code installed and Google Sheets connected (see the project README for setup). The focus here is on what to expect when someone run the tool, how to interpret what it gives clients, what to do when things need manual attention, and what the system cannot do for clients.

---

## What This Tool Does

Every semester, ATP coordinates thousands of accommodated exams. Each exam needs a time slot that doesn't conflict with the student's other classes, and a room that satisfies their accommodation requirements — capacity limits, privacy needs, reader accommodations, proctor logistics, and more. Doing this by hand is slow and error-prone given thousands of exams to be assigned.

This tool automates the two core decisions:

1. **When does the exam happen?** The system checks the student's class schedule and the instructor's approved conflict-exam options, then assigns a time slot that avoids conflicts. If the original class time works, it keeps it. If not, it tries alternatives in a priority order (same-day morning/evening, day before, day after, up to a week after).

2. **Where does the exam happen?** Once time slots are set, the system assigns each exam to a room using an optimization solver. It accounts for the following constraints: room capacity, accommodation tags (RD, PRIV, CODS), course mixing limits (no more than 3 courses per room group), and timing buffers for proctor setup. Among valid assignments, it prefers to use fewer rooms, keep a 30-minute setup buffer, and place students in Zone 1 when possible.

The output will be in the google sheet `SP26 Prelim` updated with time slots and room assignments, visualizable for clients to review and finalize.

---

## Running the Pipeline

```bash
python runner.py
```

This reads new exams from the `SP26 Input` workbook, resolves time slots, assigns rooms, and writes results back to SP26 Output. It only processes exams that haven't been handled yet (those with `Internal Status` of "Slot to be booked"), so clients can run it multiple times as new exams come in without disturbing previous assignments.

---

## Understanding the Output

### Console output after room allocation

When the solver finishes, it prints a summary like this:

```
=============================================
  Room Allocation Results
=============================================
  Exams assigned : 28 / 30
  Rooms used     : 7
=============================================
  s0001    ADW109  12/15/2024  0800-1200  Zone 1  |  5 student(s), 2 course(s)
  s0003    ASA109  12/15/2024  0800-2200  Zone 2  |  12 student(s), 3 course(s)
  ...

  Unassigned exams (2):
    Exam 68900  Student 58102  Course 10005  12/15/2024 0900-1100
    Exam 68901  Student 58103  Course 10006  12/16/2024 1700-1900
```

What to look at:

- **Exams assigned vs. total** — If this isn't 100%, some exams need manual placement. Scroll down to the unassigned list.
- **Rooms used** — The solver minimizes this, but it's worth sanity-checking that clients actually have proctor coverage for each room shown.
- **Per-room breakdown** — Check the student count and course count per room. If clients see a room with 3 courses and close to capacity, it may be logistically tight for proctoring.

### Internal Status values

The `Internal Status` column in the SP26 Prelim sheet tracks where each exam is in the pipeline:

| Status                      | Meaning                                                                     | Action needed?                                                                            |
| --------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Slot to be booked           | New exam, not yet processed — OR processed but no valid time slot was found | If this persists after a run, the system couldn't find a slot. See troubleshooting below. |
| Unresolved - no course pref | The exam's course (CRN) wasn't found in the Courses Raw Form sheet          | Add the course to the input sheet and re-run.                                             |
| Slot booked                 | Time slot assigned, waiting for room allocation                             | No action needed — run the room solver next.                                              |
| Room allocated              | Time slot and room both assigned                                            | Review and finalize.                                                                      |
| Cancelled                   | Exam was cancelled in AIM                                                   | No action needed.                                                                         |

### Updated Google Sheet

After a successful run, the `SP26 Prelim` sheet in the output workbook will have the `Date`, `Time_Start`, `Time_End`, and `Room No` columns filled in for assigned exams. The original exam time is preserved in `Original Date`, `Original Time_Start`, and `Original Time_End` so clients can always see what changed.

---

## What the System Handles Automatically

These are the rules the solver enforces — clients don't need to check these by hand for assigned exams:

- **Room capacity** — Never places more students in a room group than the room can hold.
- **RD accommodation** — If any student in a room group has the RD tag, the group is capped at 20 students regardless of physical capacity.
- **PRIV / CODS privacy** — These students are placed alone in their concurrent group within a room. (Other non-overlapping groups in the same room slot are fine.)
- **Course mixing** — No more than 3 different courses in any concurrent room group, to keep proctoring manageable.
- **Proctor setup buffer** — Every assignment guarantees at least 15 minutes of room availability before the exam starts. The solver prefers 30 minutes when possible.
- **Inter-exam gaps** — If two exams with different times share a room slot, there's at least 15 minutes between them (30 preferred).
- **Zone preference** — Zone 1 rooms are preferred over Zone 2, but never at the cost of leaving an exam unassigned.
- **NOAM / NOPM tags** — Exams for NOAM students won't start before 9 AM; exams for NOPM students won't end after 6 PM.
- **Class conflicts** — Time-slot resolution checks each student's full class schedule and all previously scheduled exams before assigning a slot.

---

## What the System Does NOT Handle

These are things clients still need to manage manually:

- **Proctor assignment** — The system assigns rooms but does not assign proctors. Clients will need to staff each room separately.
- **Room availability changes after the run** — If a room becomes unavailable (maintenance, booking conflict) after the solver has run, clients need to update the Room Availability sheet and re-run the room solver.
- **Instructor preference changes** — If an instructor updates their conflict-exam preferences after time slots have already been assigned, the affected exams won't automatically re-schedule. Clients need to reset their `Internal Status` to "Slot to be booked" and re-run Phase 1.
- **Manual overrides** — If clients manually reassign a room or time in the sheet, the system won't undo the change on the next run (it skips already-processed exams). But it also won't validate that the manual assignment satisfies all constraints.
- **Cross-student conflicts** — The time-slot resolver prevents scheduling two exams at the same time for the _same_ student. It does not consider conflicts between different students (e.g., two students who need the same private room at the same time — that's handled by the room solver).
- **Weekend room availability** — The time-slot resolver may schedule conflict exams on weekends if that's the first available alternative. Verify that rooms are actually staffed on those dates.

---

## Troubleshooting

### Some exams are unassigned after the room solver

This is the most common issue. The solver prints an unassigned list at the end of each run. Common causes and what to do:

**Not enough rooms on that date/time.** Check the Room Availability sheet — are there open slots on the date in question? If all rooms are full, clients will need to either add a room or manually negotiate a different time for the exam.

**PRIV/CODS students saturating solo rooms.** Each PRIV or CODS student needs an entire concurrent group to themselves. If clients have three private-exam students at the same time and only two small rooms, one will be unassigned. Look for rooms with availability at that time, or shift one student's time slot.

**RD tag squeezing capacity.** An RD student in a 40-person room drops its effective capacity to 20. If the room is nearly full, other students may get bumped. Consider whether a smaller dedicated room for the RD student would free up the larger room.

**4+ courses at the same time.** The solver limits each concurrent group to 3 courses. If many different courses have exams at the same time, clients may need more rooms than expected.

**No compatible room at all.** If the exam's time window doesn't fit any room's availability window (with the 15-minute buffer), there's no valid assignment. Check if the exam time can be shifted, or if a room's hours can be extended.

### "No feasible solution found"

This means the solver couldn't assign _any_ exams — not that one or two were difficult. This is rare and usually signals a data problem: empty room capacity values, date format mismatches between the exams and rooms sheets, or a corrupted input file. Check that `exams.csv` and `rooms.csv` are well-formed and that dates are formatted consistently.

### An exam stays at "Slot to be booked" after Phase 1

This means the time-slot resolver tried every instructor-approved alternative and none worked (all conflicted with the student's schedule). Check the instructor's preference columns in Courses Raw Form — if every option is "N", there are simply no alternatives to try. Contact the instructor about opening additional options.

### "Unresolved - no course pref"

The exam's CRN doesn't appear in the Courses Raw Form sheet. This usually means the instructor hasn't submitted their conflict-exam preferences yet. Follow up with them, add their response to the sheet, and re-run.

### The solver runs but takes a very long time

For typical semester loads (hundreds of exams, dozens of room slots), the solver should finish in under a minute. If it's taking significantly longer, the problem may have grown in a way that creates many tight constraints (e.g., a single date with a large number of PRIV students). Clients can check the Gurobi log output for progress — if the gap between the best solution and the bound is small, clients can interrupt and use the best solution found so far.

---

## Incremental Runs (Mid-Semester Updates)

The pipeline is designed for incremental use. When new exam requests come in during the semester:

1. The new exams appear in AIM Data with a new `Exam_ID`.
2. `get_valid_exams()` detects them as unprocessed (not yet in SP26 Prelim) and adds them with `Internal Status = "Slot to be booked"`.
3. Running the pipeline processes only these new exams. Previously assigned exams are left untouched.

If an exam is cancelled in AIM, the system automatically marks it as "Cancelled" in the output sheet on the next run.

**Important:** If clients need to re-run room allocation for _all_ exams (not just new ones) — for example, after a major room availability change — clients will need to reset the `Internal Status` of the relevant exams back to "Slot booked" and clear their `Room No` values before re-running Phase 2.

---

## Accommodation Tag Reference

| Tag                                 | What it means for scheduling                                                                                               |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **RD** (Reader/Disability)          | Room group capped at 20 students to ensure a quieter environment for reader accommodations.                                |
| **PRIV** (Private)                  | Student takes the exam alone in their concurrent group — typically for students using dictation software or reading aloud. |
| **CODS** (Code Switch)              | Same as PRIV — student is alone in their concurrent group.                                                                 |
| **NOAM** (No Morning)               | Exam cannot start before 9:00 AM. Affects time-slot resolution only.                                                       |
| **NOPM** (No Evening)               | Exam cannot end after 6:00 PM. Affects time-slot resolution only.                                                          |
| **ACDF** (Academic Disability Flag) | Tracked for reporting purposes. No effect on scheduling or room assignment.                                                |
| **COMP** (Component-based)          | Tracked for reporting purposes. No effect on scheduling or room assignment.                                                |

---

## Known Limitations

- **Processing order in Phase 1.** When multiple exams compete for the same time slot, the first exam processed gets priority. This is an inherent trade-off of the sequential algorithm — it's fast and works well in practice, but the order exams appear in the data can affect which one gets the preferred slot.
- **No global time-slot optimization.** Phase 1 assigns time slots one exam at a time. It doesn't look ahead to see whether assigning a different slot to exam A would open up a better slot for exam B. The room solver (Phase 2) is globally optimal, but time-slot resolution is greedy.
- **Manual assignments are not validated.** If clients override a room assignment by hand, the system won't check whether the updated room assignments satisfies capacity, tag, or buffer constraints. Double-check manually edited rows.
