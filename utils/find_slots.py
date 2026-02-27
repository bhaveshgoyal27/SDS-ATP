import pandas as pd
from datetime import datetime, timedelta, date

def resolve_time(course_pref, exams_df, st_timetables):
    DAY_ABBR = {'M': 'Monday', 'T': 'Tuesday', 'W': 'Wednesday',
                'R': 'Thursday', 'F': 'Friday'}

    WEEKDAY_NAME = {0: 'Monday', 1: 'Tuesday', 2: 'Wednesday',
                    3: 'Thursday', 4: 'Friday', 5: 'Saturday', 6: 'Sunday'}

    NOAM_LIMIT = datetime.strptime("09:00", "%H:%M").time()
    NOPM_LIMIT = datetime.strptime("18:00", "%H:%M").time()

    def parse_time_hhmm(t):
        return datetime.strptime(str(t).zfill(4), "%H%M").time()

    def parse_time_colon(t):
        return datetime.strptime(str(t), "%H:%M").time()

    def parse_date(d):
        return datetime.strptime(str(d), "%m/%d/%Y").date()

    def fmt_date(d):
        return d.strftime("%m/%d/%Y")

    def fmt_time(t):
        return t.strftime("%H%M")

    def times_overlap(s1, e1, s2, e2):
        return s1 < e2 and s2 < e1

    def exam_duration(orig_start_hhmm, orig_end_hhmm):
        s = datetime.combine(date.today(), parse_time_hhmm(orig_start_hhmm))
        e = datetime.combine(date.today(), parse_time_hhmm(orig_end_hhmm))
        return e - s

    def parse_tags(tags_val):
        if pd.isna(tags_val) or str(tags_val).strip() == "":
            return set()
        return {t.strip().upper() for t in str(tags_val).split("|")}

    def respects_tag_constraints(exam_start, exam_end, tags):
        if "NOAM" in tags and exam_start < NOAM_LIMIT:
            return False
        if "NOPM" in tags and exam_end > NOPM_LIMIT:
            return False
        return True

    def get_class_info(crn):
        row = course_pref[course_pref["CRN"] == crn]
        if row.empty:
            return set(), None, None
        row = row.iloc[0]
        days_raw = [d.strip() for d in str(row["Days the class is offered"]).split(",")]
        class_days = {DAY_ABBR[d] for d in days_raw if d in DAY_ABBR}
        class_start = parse_time_colon(row["Class start timings"])
        class_end   = parse_time_colon(row["Class end timings"])
        return class_days, class_start, class_end

    def get_student_timetable(student_id):
        sid = str(student_id)
        for s in st_timetables.get("students", []):
            if str(s["student_id"]) == sid:
                result = {}
                for day_entry in s.get("Timings", []):
                    slots = [(parse_time_colon(sl["start_time"]),
                              parse_time_colon(sl["end_time"]))
                             for sl in day_entry.get("Slots", [])]
                    result[day_entry["Day"]] = slots
                return result
        return {}

    def is_exam_during_own_class(exam_date, exam_start, exam_end,
                                 class_days, class_start, class_end):
        if class_start is None or class_end is None:
            return False
        exam_weekday_name = WEEKDAY_NAME.get(exam_date.weekday())
        if exam_weekday_name not in class_days:
            return False
        return times_overlap(exam_start, exam_end, class_start, class_end)

    def slot_is_free_aware(exam_date, exam_start, exam_end, timetable,
                           scheduled_exams, class_days, class_start, class_end):
        in_own_class = is_exam_during_own_class(
            exam_date, exam_start, exam_end,
            class_days, class_start, class_end
        )

        exam_weekday_name = WEEKDAY_NAME.get(exam_date.weekday())
        slots_for_day = timetable.get(exam_weekday_name, [])

        for cls_start, cls_end in slots_for_day:
            is_own_slot = (class_start is not None
                           and cls_start == class_start
                           and cls_end == class_end
                           and exam_weekday_name in class_days)

            if in_own_class and is_own_slot:
                if exam_end > class_end:
                    return False
            else:
                if times_overlap(exam_start, exam_end, cls_start, cls_end):
                    return False

        for s_date, s_start, s_end in scheduled_exams:
            if s_date == exam_date and times_overlap(exam_start, exam_end, s_start, s_end):
                return False

        return True

    def slot_is_valid_alternative(exam_date, exam_start, exam_end,
                                  timetable, scheduled_exams, tags):
        exam_weekday_name = WEEKDAY_NAME.get(exam_date.weekday())
        slots_for_day = timetable.get(exam_weekday_name, [])

        for cls_start, cls_end in slots_for_day:
            if times_overlap(exam_start, exam_end, cls_start, cls_end):
                return False

        for s_date, s_start, s_end in scheduled_exams:
            if s_date == exam_date and times_overlap(exam_start, exam_end, s_start, s_end):
                return False

        return respects_tag_constraints(exam_start, exam_end, tags)

    CANDIDATE_RULES = [
        ("8:00 am the day of the exam",         "5:00 pm the day of the exam",         0),
        ("8:00 am the day BEFORE the exam",     "5:00 pm the day BEFORE the exam",    -1),
        ("8:00 am the day AFTER the exam",      "5:00 pm the day AFTER the exam",      1),
        ("8:00 am up to a week AFTER the exam", "5:00 pm up to a week AFTER the exam", None),
    ]

    def try_alternative_slot(candidate_date, anchor_time, duration,
                             timetable, scheduled_exams, tags):
        exam_start = anchor_time
        exam_end   = (datetime.combine(candidate_date, exam_start) + duration).time()
        if slot_is_valid_alternative(candidate_date, exam_start, exam_end,
                                     timetable, scheduled_exams, tags):
            return exam_start, exam_end
        return None

    def book_slot(idx, candidate_date, start_t, end_t, sch_list):
        exams_df.at[idx, "Date"]            = fmt_date(candidate_date)
        exams_df.at[idx, "Time_Start"]      = fmt_time(start_t)
        exams_df.at[idx, "Time_End"]        = fmt_time(end_t)
        exams_df.at[idx, "Internal Status"] = "Slot booked"
        sch_list.append((candidate_date, start_t, end_t))

    scheduled = {}

    for idx, exam_row in exams_df.iterrows():
        student_id = exam_row["Student_ID"]
        crn        = exam_row["Course_ID"]
        orig_date  = parse_date(exam_row["Original Date"])
        orig_start = exam_row["Original Time_Start"]
        orig_end   = exam_row["Original Time_End"]
        duration   = exam_duration(orig_start, orig_end)
        tags       = parse_tags(exam_row.get("Tags", ""))

        timetable  = get_student_timetable(student_id)
        sch_list   = scheduled.setdefault(student_id, [])

        orig_start_t = parse_time_hhmm(orig_start)
        orig_end_t   = parse_time_hhmm(orig_end)

        class_days, class_start, class_end = get_class_info(crn)

        pref_row_df = course_pref[course_pref["CRN"] == crn]
        pref_row    = pref_row_df.iloc[0] if not pref_row_df.empty else None

        orig_free = slot_is_free_aware(
            orig_date, orig_start_t, orig_end_t,
            timetable, sch_list,
            class_days, class_start, class_end
        )

        if orig_free and respects_tag_constraints(orig_start_t, orig_end_t, tags):
            book_slot(idx, orig_date, orig_start_t, orig_end_t, sch_list)
            continue

        if pref_row is None:
            exams_df.at[idx, "Internal Status"] = "Unresolved - no course pref"
            continue

        booked = False

        for am_col, pm_col, day_offset in CANDIDATE_RULES:
            if booked:
                break

            prefer_am = str(pref_row.get(am_col, "N")).strip().upper() == "Y"
            prefer_pm = str(pref_row.get(pm_col, "N")).strip().upper() == "Y"

            if not prefer_am and not prefer_pm:
                continue

            anchor = datetime.strptime("08:00", "%H:%M").time() if prefer_am \
                else datetime.strptime("17:00", "%H:%M").time()

            if "NOAM" in tags and anchor < NOAM_LIMIT:
                anchor = NOAM_LIMIT

            if day_offset is not None:
                candidate_date = orig_date + timedelta(days=day_offset)
                result = try_alternative_slot(
                    candidate_date, anchor, duration, timetable, sch_list, tags)
                if result:
                    book_slot(idx, candidate_date, result[0], result[1], sch_list)
                    booked = True
            else:
                for delta in range(2, 8):
                    candidate_date = orig_date + timedelta(days=delta)
                    result = try_alternative_slot(
                        candidate_date, anchor, duration, timetable, sch_list, tags)
                    if result:
                        book_slot(idx, candidate_date, result[0], result[1], sch_list)
                        booked = True
                        break

        if not booked:
            exams_df.at[idx, "Internal Status"] = "Slot to be booked"

    return exams_df