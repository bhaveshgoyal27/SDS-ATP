import json
import datetime
import pandas as pd
from utils.access_google_sheets import get_sheet_as_df, update_sheet_with_df, update_sheet_with_df_with_columns
from utils.find_slots import resolve_time

class Prelims:
    def __init__(self):
        self.valid_status = ["Slot to be booked", "Slot booked", "Room allocated", "Completed", "Cancelled"]
        pass

    def runner(self):
        course_pref = self.process_course_list()
        exams_df = self.get_valid_exams()
        st_timetables = self.get_timetables()
        self.get_time_slots(course_pref, exams_df, st_timetables)
        # rooms_df = self.get_rooms()
        # alloted_df = self.allot_rooms(rooms_df, time_resolved_df)
        pass

    def process_course_list(self):
        df = get_sheet_as_df("SP26 Input", "Courses Raw Form")
        column_name = 'If there is an academic conflict with a scheduled exam, the conflict exam options are...'
        values = ["8:00 am the day of the exam", "5:00 pm the day of the exam", "8:00 am the day BEFORE the exam",
                  "5:00 pm the day BEFORE the exam", "8:00 am the day AFTER the exam",
                  "5:00 pm the day AFTER the exam", "8:00 am up to a week AFTER the exam",
                  "5:00 pm up to a week AFTER the exam",
                  "Conflict exams will be managed internally, the student should contact the instructor", "Other"]
        for v in values:
            df[v] = df[column_name].apply( lambda lst: 'Y' if v in lst else 'N')
        update_sheet_with_df("FA25 NEW MOCK", "Sign Ups", df)
        v1 = ["CRN", "Class start timings", "Class end timings", "Days the class is offered"]
        v1.extend(values)
        df = df[v1]
        update_sheet_with_df("SP26 Input", "Courses Form filtered", df)
        return df

    def get_valid_exams(self):
        aim_df = get_sheet_as_df("SP26 Input", "AIM Data")
        internal_df = get_sheet_as_df("SP26 Output", "SP26 Prelim")
        cancelled_exams = aim_df.loc[aim_df['Status'] == 'Cancelled', 'Exam_ID'].tolist()
        internal_df.loc[
            internal_df['Exam_ID'].isin(cancelled_exams),['Status', 'Internal Status']
        ] = ["Cancelled", "Cancelled"]
        aim_df = aim_df.query("Status=='Active'")
        aim_exams = list(aim_df["Exam_ID"])
        internal_exams = internal_df.loc[aim_df['Status'] == 'Active', 'Exam_ID'].tolist()
        new_exams = list(set(aim_exams)-set(internal_exams))
        aim_df = aim_df.query("Exam_ID in @new_exams")
        aim_df.rename(columns={"Date": "Original Date", "Time_Start": "Original Time_Start",
                               "Time_End": "Original Time_End"}, inplace=True)
        aim_df["Date"] = None
        aim_df["Time_Start"] = None
        aim_df["Time_End"] = None
        aim_df["Room No"] = None
        aim_df["Internal Status"] = "Slot to be booked"
        aim_df = aim_df[["Student_ID","Exam_ID","Course_ID","Original Date","Original Time_Start","Original Time_End",
                         "Date","Time_Start","Time_End","Multiplier","Status","Tags","Room No","Internal Status"]]
        internal_df = pd.concat([internal_df, aim_df], ignore_index=True)
        update_sheet_with_df("SP26 Output", "SP26 Prelim", internal_df)
        to_be_booked = internal_df.loc[internal_df['Internal Status'] == 'Slot to be booked']
        # df['DATE'] = pd.to_datetime(df['DATE'], format='%m/%d/%Y')
        # today = pd.Timestamp.today().normalize()
        # df_filtered = df.query("DATE >= @today")
        return to_be_booked

    def get_timetables(self):
        path = "timetables/student_timetable.json"
        with open(path, "r") as file:
            timetables = json.load(file)
        return timetables

    def get_time_slots(self, course_pref, exams_df, st_timetables):
        new_df = resolve_time(course_pref, exams_df, st_timetables)
        new_df.to_csv("result1.csv", index=False)
        update_sheet_with_df_with_columns("SP26 Output", "SP26 Prelim", new_df, "Exam_ID")


