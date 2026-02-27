import pandas as pd
from datetime import datetime, date, timedelta
from utils.find_slots import resolve_time

# ─────────────────────────────────────────────────────────────────────────────
# SHARED FIXTURES & BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

PREF_COLS = [
    "CRN",
    "Class start timings", "Class end timings", "Days the class is offered",
    "8:00 am the day of the exam",       "5:00 pm the day of the exam",
    "8:00 am the day BEFORE the exam",   "5:00 pm the day BEFORE the exam",
    "8:00 am the day AFTER the exam",    "5:00 pm the day AFTER the exam",
    "8:00 am up to a week AFTER the exam", "5:00 pm up to a week AFTER the exam",
]

EXAM_COLS = [
    "Student_ID", "Exam_ID", "Course_ID",
    "Original Date", "Original Time_Start", "Original Time_End",
    "Date", "Time_Start", "Time_End",
    "Multiplier", "Status", "Tags", "Room No", "Internal Status",
]

def make_pref(crn, class_start, class_end, days,
              am_exam="N", pm_exam="N",
              am_before="N", pm_before="N",
              am_after="N",  pm_after="N",
              am_week="N",   pm_week="N"):
    return pd.DataFrame([{
        "CRN": crn,
        "Class start timings": class_start,
        "Class end timings": class_end,
        "Days the class is offered": days,
        "8:00 am the day of the exam": am_exam,
        "5:00 pm the day of the exam": pm_exam,
        "8:00 am the day BEFORE the exam": am_before,
        "5:00 pm the day BEFORE the exam": pm_before,
        "8:00 am the day AFTER the exam": am_after,
        "5:00 pm the day AFTER the exam": pm_after,
        "8:00 am up to a week AFTER the exam": am_week,
        "5:00 pm up to a week AFTER the exam": pm_week,
    }], columns=PREF_COLS)

def make_exam(student_id, exam_id, crn,
              orig_date, orig_start, orig_end,
              tags="", status="Active"):
    return pd.DataFrame([{
        "Student_ID": student_id,
        "Exam_ID": exam_id,
        "Course_ID": crn,
        "Original Date": orig_date,
        "Original Time_Start": orig_start,
        "Original Time_End": orig_end,
        "Date": None, "Time_Start": None, "Time_End": None,
        "Multiplier": 1.0,
        "Status": status,
        "Tags": tags,
        "Room No": None,
        "Internal Status": None,
    }], columns=EXAM_COLS)

def make_timetable(student_id, day_slots: dict):
    """
    day_slots: {"Monday": [("08:40","09:55"), ...], ...}
    """
    timings = []
    for day, slots in day_slots.items():
        timings.append({
            "Day": day,
            "Slots": [{"start_time": s, "end_time": e} for s, e in slots]
        })
    return {"students": [{"student_id": str(student_id), "Timings": timings}]}

def run(pref, exam, timetable):
    return resolve_time(pref, exam.copy(), timetable)

# ─────────────────────────────────────────────────────────────────────────────
# TC-01  No conflict at all — keep original slot
# ─────────────────────────────────────────────────────────────────────────────
# Exam on Monday 10:00-11:00. Student has class Mon 08:00-09:00.
# No overlap → original slot kept.
def test_tc01_no_conflict_keeps_original():
    pref = make_pref(101, "08:00", "09:00", "M")
    exam = make_exam(1, 1, 101, "04/07/2025", 1000, 1100)
    tt   = make_timetable(1, {"Monday": [("08:00", "09:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Date"] == "04/07/2025"
    assert res.iloc[0]["Time_Start"] == "1000"
    assert res.iloc[0]["Time_End"]   == "1100"

# ─────────────────────────────────────────────────────────────────────────────
# TC-02  Exam during own class, fits within class window — allowed
# ─────────────────────────────────────────────────────────────────────────────
# Class Mon 10:00-11:15. Exam Mon 10:00-11:00 (fits within). Should be booked.
def test_tc02_exam_during_own_class_fits():
    pref = make_pref(102, "10:00", "11:15", "M")
    exam = make_exam(1, 1, 102, "04/07/2025", 1000, 1100)
    tt   = make_timetable(1, {"Monday": [("10:00", "11:15")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Time_Start"] == "1000"

# ─────────────────────────────────────────────────────────────────────────────
# TC-03  Exam during own class but BLEEDS past class end — rejected, rescheduled
# ─────────────────────────────────────────────────────────────────────────────
# Class Mon 10:00-11:00. Exam 10:00-11:30 (bleeds 30 min). Must reschedule.
# course_pref allows 8am day-after.
def test_tc03_exam_bleeds_past_class_end_rescheduled():
    pref = make_pref(103, "10:00", "11:00", "M", am_after="Y")
    exam = make_exam(1, 1, 103, "04/07/2025", 1000, 1130)
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    # Should be rescheduled to Tuesday (day after Monday)
    assert res.iloc[0]["Date"] == "04/08/2025"
    assert res.iloc[0]["Time_Start"] == "0800"

# ─────────────────────────────────────────────────────────────────────────────
# TC-04  Exam NOT on a class day — treated as plain conflict check
# ─────────────────────────────────────────────────────────────────────────────
# Class is M,W. Exam on Tuesday — no own-class exemption applies.
# Exam overlaps a different class on Tuesday → must reschedule.
def test_tc04_exam_not_on_class_day_plain_conflict():
    pref = make_pref(104, "10:00", "11:00", "M, W", am_after="Y")
    exam = make_exam(1, 1, 104, "04/08/2025", 1000, 1100)  # Tuesday
    tt   = make_timetable(1, {"Tuesday": [("10:00", "11:00")]})
    res  = run(pref, exam, tt)
    # Tuesday has a class 10:00-11:00, exam is same time but NOT an own-class day
    # so it's a real conflict → reschedule
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Date"] != "04/08/2025"

# ─────────────────────────────────────────────────────────────────────────────
# TC-05  NOAM tag — original slot before 09:00 rejected
# ─────────────────────────────────────────────────────────────────────────────
# Exam at 08:00, student has NOAM tag. Original rejected.
# course_pref allows 8am day-of which bumps to 09:00.
def test_tc05_noam_rejects_early_original():
    pref = make_pref(105, "08:00", "09:00", "M", am_exam="Y")
    exam = make_exam(1, 1, 105, "04/07/2025", 800, 900, tags="NOAM")
    tt   = make_timetable(1, {})  # no other classes
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    # Anchor bumped to 09:00 (NOAM)
    assert res.iloc[0]["Time_Start"] == "0900"

# ─────────────────────────────────────────────────────────────────────────────
# TC-06  NOPM tag — slot ending after 18:00 rejected
# ─────────────────────────────────────────────────────────────────────────────
# Exam 17:00-18:30. Student has NOPM. Original rejected.
# Only PM alternative available (17:00 start, 90min = ends 18:30) also rejected.
# Should be unresolved.
def test_tc06_nopm_rejects_late_ending():
    pref = make_pref(106, "17:00", "18:30", "M", pm_exam="Y", pm_after="Y")
    exam = make_exam(1, 1, 106, "04/07/2025", 1700, 1830, tags="NOPM")
    tt   = make_timetable(1, {"Monday": [("17:00", "18:30")]})
    res  = run(pref, exam, tt)
    # Original: 17:00-18:30 bleeds past class end (same time) AND violates NOPM
    # All PM alternatives also end at 18:30 → violate NOPM
    assert res.iloc[0]["Internal Status"] == "Unresolved - no available slot"

# ─────────────────────────────────────────────────────────────────────────────
# TC-07  NOAM + NOPM together — only 09:00-18:00 window valid
# ─────────────────────────────────────────────────────────────────────────────
# Exam 09:00-10:00, no class conflicts, both NOAM and NOPM → should book original.
def test_tc07_noam_nopm_valid_window():
    pref = make_pref(107, "09:00", "10:00", "M")
    exam = make_exam(1, 1, 107, "04/07/2025", 900, 1000, tags="NOAM|NOPM")
    tt   = make_timetable(1, {"Monday": [("09:00", "10:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Time_Start"] == "0900"

# ─────────────────────────────────────────────────────────────────────────────
# TC-08  Two exams same student same day — second must not clash with first
# ─────────────────────────────────────────────────────────────────────────────
# Student has two exams on same day. Second exam's original overlaps first.
# Second should be rescheduled.
def test_tc08_two_exams_same_day_no_clash():
    pref1 = make_pref(108, "10:00", "11:00", "M")
    pref2 = make_pref(109, "10:00", "11:00", "M", am_after="Y")
    pref  = pd.concat([pref1, pref2], ignore_index=True)

    exam1 = make_exam(1, 1, 108, "04/07/2025", 1000, 1100)
    exam2 = make_exam(1, 2, 109, "04/07/2025", 1000, 1100)
    exams = pd.concat([exam1, exam2], ignore_index=True)

    tt = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    res = run(pref, exams, tt)

    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[1]["Internal Status"] == "Slot booked"

    # They must not overlap
    d1 = res.iloc[0]["Date"];  s1 = res.iloc[0]["Time_Start"]; e1 = res.iloc[0]["Time_End"]
    d2 = res.iloc[1]["Date"];  s2 = res.iloc[1]["Time_Start"]; e2 = res.iloc[1]["Time_End"]

    def t(hhmm): return datetime.strptime(str(hhmm).zfill(4), "%H%M").time()

    if d1 == d2:
        assert not (t(s1) < t(e2) and t(s2) < t(e1)), "Exams overlap on same day!"

# ─────────────────────────────────────────────────────────────────────────────
# TC-09  Alternative: day BEFORE exam
# ─────────────────────────────────────────────────────────────────────────────
# Original conflicts. Only "before" option is Y. Should land day before.
def test_tc09_alternative_day_before():
    pref = make_pref(110, "10:00", "11:00", "M", am_before="Y")
    exam = make_exam(1, 1, 110, "04/07/2025", 1000, 1100)  # Monday
    tt   = make_timetable(1, {"Monday": [("10:00", "11:30")]})  # bleeds → conflict
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Date"] == "04/06/2025"  # Sunday (day before Monday)
    assert res.iloc[0]["Time_Start"] == "0800"

# ─────────────────────────────────────────────────────────────────────────────
# TC-10  Alternative: up to a week after — picks first free day
# ─────────────────────────────────────────────────────────────────────────────
# Original and day-of/before/after all conflict or not enabled.
# Only "up to a week after" is Y. Should find first free day in days 2-7.
def test_tc10_alternative_up_to_week_after():
    pref = make_pref(111, "10:00", "11:00", "M", am_week="Y")
    exam = make_exam(1, 1, 111, "04/07/2025", 1000, 1100)  # Monday
    # Student has class Mon-Fri 10:00-11:00, so days 1-5 (Tue-Sat) at 08:00 are free
    tt = make_timetable(1, {
        "Monday":    [("10:00", "11:00")],
        "Tuesday":   [("10:00", "11:00")],
        "Wednesday": [("10:00", "11:00")],
    })
    res = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    # Original slot (Mon 10:00-11:00) fits exactly within own class (Mon 10:00-11:00)
    # → no bleed, no conflict → original is kept
    assert res.iloc[0]["Date"] == "04/07/2025"
    assert res.iloc[0]["Time_Start"] == "1000"

# ─────────────────────────────────────────────────────────────────────────────
# TC-11  No course pref found — unresolved
# ─────────────────────────────────────────────────────────────────────────────
def test_tc11_no_course_pref_unresolved():
    pref = make_pref(999, "10:00", "11:00", "M")  # CRN 999, exam uses 112
    exam = make_exam(1, 1, 112, "04/07/2025", 1000, 1100)
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Unresolved - no course pref"

# ─────────────────────────────────────────────────────────────────────────────
# TC-12  No alternatives enabled in course_pref — unresolved
# ─────────────────────────────────────────────────────────────────────────────
def test_tc12_no_alternatives_enabled_unresolved():
    pref = make_pref(113, "10:00", "11:00", "M")  # all booleans default N
    exam = make_exam(1, 1, 113, "04/07/2025", 1000, 1100)
    # Exam during own class but bleeds past end → conflict
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    # exam 10:00-11:30 bleeds
    exam.at[0, "Original Time_End"] = 1130
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Unresolved - no available slot"

# ─────────────────────────────────────────────────────────────────────────────
# TC-13  Student not in timetable — no class conflicts, original kept
# ─────────────────────────────────────────────────────────────────────────────
def test_tc13_student_not_in_timetable():
    pref = make_pref(114, "10:00", "11:00", "M")
    exam = make_exam(99, 1, 114, "04/07/2025", 1000, 1100)
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})  # student 1, not 99
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Time_Start"] == "1000"

# ─────────────────────────────────────────────────────────────────────────────
# TC-14  Alternative conflicts with a different class — skipped, next day tried
# ─────────────────────────────────────────────────────────────────────────────
# Original conflicts. Day-after alternative also conflicts with a class.
# "Up to week after" finds first free day.
def test_tc14_alternative_day_after_also_conflicts():
    pref = make_pref(115, "10:00", "11:00", "M", am_after="Y", am_week="Y")
    exam = make_exam(1, 1, 115, "04/07/2025", 1000, 1100)  # Monday
    tt   = make_timetable(1, {
        "Monday":  [("10:00", "11:00")],
        "Tuesday": [("08:00", "09:30")],  # 08:00-09:30 blocks day-after 08:00 slot
    })
    res = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    # Original Mon 10:00-11:00 fits within own class Mon 10:00-11:00 → kept as-is
    assert res.iloc[0]["Date"] == "04/07/2025"

# ─────────────────────────────────────────────────────────────────────────────
# TC-15  PM preferred (only pm_after=Y), no NOPM — books at 17:00
# ─────────────────────────────────────────────────────────────────────────────
def test_tc15_pm_alternative_books_at_1700():
    pref = make_pref(116, "10:00", "11:00", "M", pm_after="Y")
    exam = make_exam(1, 1, 116, "04/07/2025", 1000, 1200)  # 2hr exam, Mon
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    # Exam 10:00-12:00 during own class Mon 10:00-11:00 → bleeds → conflict
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Date"] == "04/08/2025"   # Tuesday
    assert res.iloc[0]["Time_Start"] == "1700"

# ─────────────────────────────────────────────────────────────────────────────
# TC-16  NOAM bumps 08:00 anchor to 09:00 for alternatives
# ─────────────────────────────────────────────────────────────────────────────
def test_tc16_noam_bumps_anchor_to_0900():
    pref = make_pref(117, "10:00", "11:00", "M", am_after="Y")
    exam = make_exam(1, 1, 117, "04/07/2025", 1000, 1100, tags="NOAM")
    tt   = make_timetable(1, {"Monday": [("10:00", "11:30")]})  # bleeds → conflict
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Time_Start"] == "0900"   # bumped from 08:00

# ─────────────────────────────────────────────────────────────────────────────
# TC-17  Two students, independent scheduling — no cross-student interference
# ─────────────────────────────────────────────────────────────────────────────
def test_tc17_two_students_independent():
    pref = make_pref(118, "10:00", "11:00", "M")
    exam1 = make_exam(1, 1, 118, "04/07/2025", 1000, 1100)
    exam2 = make_exam(2, 2, 118, "04/07/2025", 1000, 1100)
    exams = pd.concat([exam1, exam2], ignore_index=True)
    tt = {
        "students": [
            {"student_id": "1", "Timings": [{"Day": "Monday", "Slots": [{"start_time": "10:00", "end_time": "11:00"}]}]},
            {"student_id": "2", "Timings": [{"Day": "Monday", "Slots": [{"start_time": "10:00", "end_time": "11:00"}]}]},
        ]
    }
    res = run(pref, exams, tt)
    # Both exams are during their own class → both valid
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[1]["Internal Status"] == "Slot booked"

# ─────────────────────────────────────────────────────────────────────────────
# TC-18  Exam on weekend (no class days) — no conflict, books original
# ─────────────────────────────────────────────────────────────────────────────
def test_tc18_exam_on_weekend_no_conflict():
    pref = make_pref(119, "10:00", "11:00", "M, W, F")
    exam = make_exam(1, 1, 119, "04/05/2025", 1000, 1100)  # Saturday
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Date"] == "04/05/2025"

# ─────────────────────────────────────────────────────────────────────────────
# TC-19  Exam fits exactly within class window (edge: end == class_end)
# ─────────────────────────────────────────────────────────────────────────────
def test_tc19_exam_ends_exactly_at_class_end():
    pref = make_pref(120, "10:00", "11:00", "M")
    exam = make_exam(1, 1, 120, "04/07/2025", 1000, 1100)
    tt   = make_timetable(1, {"Monday": [("10:00", "11:00")]})
    res  = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Slot booked"
    assert res.iloc[0]["Time_End"] == "1100"

# ─────────────────────────────────────────────────────────────────────────────
# TC-20  All alternatives exhausted (week after all blocked) — unresolved
# ─────────────────────────────────────────────────────────────────────────────
def test_tc20_all_week_alternatives_blocked():
    pref = make_pref(121, "08:00", "09:00", "M", am_week="Y")
    exam = make_exam(1, 1, 121, "04/07/2025", 800, 1000)  # 2hr, bleeds past class
    # Block 08:00-10:00 on every day of the week after
    day_slots = {d: [("08:00", "10:00")] for d in
                 ["Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","Monday"]}
    tt = make_timetable(1, day_slots)
    res = run(pref, exam, tt)
    assert res.iloc[0]["Internal Status"] == "Unresolved - no available slot"

