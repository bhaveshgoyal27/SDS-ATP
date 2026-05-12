# SDS-ATP Exam Scheduling System
Automated exam scheduling and room allocation for Cornell's Alternative Testing Program (ATP) within Student Disability Services (SDS). The system ingests student exam requests, resolves time-slot conflicts based on instructor preferences and student timetables, and assigns exams to accommodation-appropriate rooms using a Gurobi Integer Linear Programming (ILP) solver — replacing a manual process that previously required staff to juggle thousands of accommodated exams per semester across constraints on room capacities, accommodation tags, course mixing limits, and timing buffers.
 
## Stakeholder / Client
- Main client: Anton Ochoa (SDS Testing Coordinator, Disability Accommodations)
- Nibras Islam (Administrative Assistant - ATP)
- David B. Shmoys (Laibe/Acheson Professor of Business Management and Leadership St)
 
## Team Members
 
Bhavesh Goyal (bg487@cornell.edu), Youlun Jiang (yj622@cornell.edu)
 
## Tech Stack
| Layer | Tools |
|-------|-------|
| Language | Python 3 |
| Optimization | Gurobi (gurobipy) — Integer Linear Programming solver |
| Data handling | pandas |
| Data source / output | Google Sheets API |
| Development | Claude Code |
## Quickstart
### Prerequisites
- Python 3.x
- A valid [Gurobi license](https://www.gurobi.com/academia/academic-program-and-licenses/) (free academic licenses available)
 
#### 1. Clone the repo
```bash
git clone https://github.com/bhaveshgoyal27/SDS-ATP
```
#### 2. Setup Google Sheets
The pipeline reads and writes data through Google Sheets using `get_sheet_as_df()` and `update_sheet_with_df_with_columns()` in `utils/access_google_sheets.py`. You can request access to our existing dataset — [`SP26 Input`](https://docs.google.com/spreadsheets/d/1tW0w2RplGNepea-NPtnmjBRx7JGCRdU_pulBitOxg5Y/edit?usp=sharing) and [`SP26 Output`](https://docs.google.com/spreadsheets/d/1R96mbi-p1sbpjBWJH8FOt8GU_e5pLmQPz35_QO48baA/edit?usp=sharing) workbooks.
**Alternatively**, if you want to create your own workbooks, update the `file_name` arguments in `service/prelims.py` to match your workbook names and structure the sheets as follows:
- **Input workbook** (default: `"SP26 Input"`): must contain the following sheets:

| Sheet name | Purpose | Required columns |
|------------|---------|-----------------|
| `Courses Raw Form` | Instructor conflict-exam preferences | `CRN`, `Class start timings`, `Class end timings`, `Days the class is offered`, + multi-select preference column (exploded into 10 binary columns) |
| `AIM Data` | Exam records from the AIM system | `Exam_ID`, `Student_ID`, `Course_ID`, `Date`, `Time_Start`, `Time_End`, `Multiplier`, `Status`, `Tags` |
| `LIV25` | Master room list | `Location_Name`, `Testing capacity`, `Zone`, `S25` (Y/N), `AIM` (Y/N) |
| `Room Availability` | Room date/time windows | `slot_id`, `Location_Name`, `Date`, `Time_Start`, `Time_End` |

- **Output workbook** (default: `"SP26 Output"`): must contain:

| Sheet name | Purpose | Required columns |
|------------|---------|-----------------|
| `SP26 Prelim` | Internal tracking sheet | `Exam_ID`, `Student_ID`, `Course_ID`, `Original Date`, `Original Time_Start`, `Original Time_End`, `Date`, `Time_Start`, `Time_End`, `Room No`, `Internal Status`, `Status`, `Tags`, `Multiplier` |
- **Authentication:** Place your Google service account credentials JSON at `keys/atp-poc1-4e72f50119bc.json` (or update the path in `_get_client()` in `utils/sheets.py`). The service account must have Editor access to both workbooks.
 
#### 2. Install the dependencies
 
```bash
pip install gurobipy pandas gspread
```
 
#### 3. Run the pipeline
```bash
python runner.py
```
The pipeline reads from the configured Google Sheets workbook (`SP26 Input`), runs time-slot resolution and room allocation, and writes results back to `SP26 Output`.

## Repository Map
```
├── service/
│   └── prelims.py              # Pipeline orchestrator (Prelims class)
├── utils/
│   ├── find_slots.py           # Phase 1 — Time-slot resolution algorithm
│   └── gurobi_solver.py        # Phase 2 — ILP room allocation (allot_rooms)
├── timetables/
│   └── student_timetable.json  # Student weekly class schedules
├── test/
│   └── test_resolve_slots.py   # Unit tests for time-slot resolution
│   docs/
│   └── architecture.md         # 
│   └── workflow_analysis.md    # 
├── exams.csv                   # Exams ready for room assignment (generated after running the code) 
├── rooms.csv                   # Room availability slots (generated after running the code) 
└── README.md
