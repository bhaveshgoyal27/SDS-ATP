# Working system setup (SDS-ATP)

This document walks through getting a new machine ready to run the SDS-ATP pipeline end to end: Python environment, Google Sheets access, the **SP26 Input** and **SP26 Output** workbooks, and Gurobi.

For how the pipeline behaves once it runs, see `docs/workflow_analysis.md` and `docs/architecture.md`.

---

## 1. Clone the repository and open a terminal

1. Clone this repo to your machine (same command on every OS):
  ```bash
   git clone https://github.com/bhaveshgoyal27/SDS-ATP.git
   cd SDS-ATP
  ```
2. Stay in the repository root for the steps below (the folder that contains `runner.py`, `service/`, and `utils/`).

**Terminals:** use **PowerShell** or **Command Prompt** on Windows; use **Terminal** (or iTerm) on macOS; use your distro’s terminal on Linux (bash or zsh both work).

---

## 2. Python virtual environment and packages

1. Use a recent **Python 3** (the project has been used with 3.12). Check that Python is on your `PATH`:
  - **Windows:** `python --version`
  - **macOS / Linux:** `python3 --version` (on some Linux images the command is still `python`; use whichever prints Python 3.)
2. Create a virtual environment in the repo root:

  | OS                             | Create venv             |
  | ------------------------------ | ----------------------- |
  | **Windows (PowerShell / CMD)** | `python -m venv .venv`  |
  | **macOS / Linux**              | `python3 -m venv .venv` |

3. Activate the venv (do this in **every new terminal** before `pip` or `python`):

  | OS                              | Activate                       |
  | ------------------------------- | ------------------------------ |
  | **Windows — PowerShell**        | `.\.venv\Scripts\Activate.ps1` |
  | **Windows — Command Prompt**    | `.\.venv\Scripts\activate.bat` |
  | **macOS / Linux — bash or zsh** | `source .venv/bin/activate`    |

   **macOS / Linux note:** if PowerShell says `Activate.ps1` cannot be loaded, you are on Windows instructions; on macOS/Linux always use `source .venv/bin/activate`.
   **Linux note:** if `ensurepip` is missing, install the `python3-venv` package for your distribution (e.g. Debian/Ubuntu: `sudo apt install python3-venv`), then recreate `.venv`.
4. Upgrade `pip` (optional but recommended):
  ```bash
   python -m pip install --upgrade pip
  ```
   On macOS/Linux, if `python` is not found inside the venv, use `python3 -m pip install --upgrade pip` instead.
5. Install Python dependencies used by the code (there is no `requirements.txt` in the tree yet; install at least):
  ```bash
   pip install pandas gspread oauth2client
  ```
6. Install **Gurobi’s Python bindings** after you have a Gurobi license (see [Section 6](#6-gurobi-license-and-gurobipy)). Typical install:
  ```bash
   pip install gurobipy
  ```
   If your environment requires the full Gurobi installer from Gurobi’s website, follow their instructions first; then ensure `import gurobipy` works inside the same venv.

---

## 3. Local files the runner expects

- `**timetables/student_timetable.json**` — already in the repo; the pipeline reads it in `Prelims.get_timetables()`. Replace or refresh this file only when your team supplies an updated timetable export.
- `**keys/**` — create this directory at the repo root if it does not exist. It is listed in `.gitignore`; **never commit** service account JSON or license files.
  - **macOS / Linux:** from the repo root run `mkdir -p keys`, then move your downloaded JSON into `keys/` (for example `mv ~/Downloads/your-key.json keys/`).
  - **Windows:** create a folder named `keys` in the repo root in Explorer, or run `mkdir keys` in PowerShell.

---

## 4. Google Sheets credentials (service account)

The code uses **gspread** with a **Google Cloud service account** JSON key file (`oauth2client.service_account.ServiceAccountCredentials`). The default path is set in `utils/access_google_sheets.py` in `_get_client()` (parameter `creds_json_path`).

### 4.1 Create or reuse a Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select an existing project or create a new one dedicated to this automation (recommended for least privilege).

### 4.2 Enable APIs

Enable both of the following for that project:

- **Google Sheets API**
- **Google Drive API** (the code requests Drive scope so `gspread` can open spreadsheets by title)

Use **APIs & Services → Library** in the console, search for each API, and click **Enable**.

### 4.3 Create a service account and key

1. Go to **APIs & Services → Credentials**.
2. **Create credentials → Service account**. Give it a clear name (for example `sds-atp-sheets`).
3. After the account exists, open it → **Keys → Add key → Create new key → JSON**. Download the JSON file.

### 4.4 Install the key locally (no commits)

1. Save the downloaded JSON under the repo’s `**keys/`** directory, for example `keys/your-project-service-account.json`.
2. Point the code at that file: either
  - rename/copy to match the filename already referenced in `_get_client()` in `utils/access_google_sheets.py`, **or**
  - edit `_get_client()` so `creds_json_path` is your file’s path relative to the repo root.

### 4.5 What to share with spreadsheet owners

From the JSON file, copy the `**client_email`** (it looks like `something@PROJECT_ID.iam.gserviceaccount.com`). Spreadsheet owners must **share each Google Sheet** that the pipeline touches with this email, with at least **Editor** access if the pipeline writes rows (this project does).

Keep the JSON private; treat it like a password.

---

## 5. Raise access to **SP26 Input** and **SP26 Output**

The pipeline opens workbooks by **title** using `gspread` (`client.open("SP26 Input")`, etc.). The Google Sheet’s **name in Drive** must therefore stay **exactly** `SP26 Input` and `SP26 Output` unless you change those strings in `service/prelims.py`.

### 5.0 Canonical spreadsheet links

Use these links to open the correct files (confirm the title in the browser tab matches the table below):


| Spreadsheet title (must match code) | Role                                                                | Open in Google Sheets                                                                                               |
| ----------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **SP26 Input**                      | Source data: courses, AIM, rooms, room availability                 | [SP26 Input](https://docs.google.com/spreadsheets/d/1tW0w2RplGNepea-NPtnmjBRx7JGCRdU_pulBitOxg5Y/edit?usp=sharing)  |
| **SP26 Output**                     | Working / output workbook for prelim scheduling and room assignment | [SP26 Output](https://docs.google.com/spreadsheets/d/1R96mbi-p1sbpjBWJH8FOt8GU_e5pLmQPz35_QO48baA/edit?usp=sharing) |


**Spreadsheet IDs** (for support / API use; the current code uses titles, not IDs):

- SP26 Input: `1tW0w2RplGNepea-NPtnmjBRx7JGCRdU_pulBitOxg5Y`
- SP26 Output: `1R96mbi-p1sbpjBWJH8FOt8GU_e5pLmQPz35_QO48baA`

### 5.1 Workbooks to share with the service account

Share these **two** spreadsheets with the service account `**client_email`** as **Editor** (the pipeline reads and writes). In each file: **Share** → paste the service account email → **Editor** → send.

If someone duplicates the file in Drive, the duplicate gets a new title (for example “Copy of SP26 Input”) and the code will **not** find it until the title is renamed back or `service/prelims.py` is updated.

### 5.2 Tabs (worksheets) that must exist inside each file

The code in `service/prelims.py` expects these **exact worksheet names**:

**Inside `SP26 Input`**


| Worksheet name          | Used for                                       |
| ----------------------- | ---------------------------------------------- |
| `Courses Raw Form`      | Course preferences and conflict options (read) |
| `Courses Form filtered` | Filtered course columns (written)              |
| `AIM Data`              | Active/cancelled exams (read)                  |
| `LIV25`                 | Room rows merged with availability (read)      |
| `Room Availability`     | Room metadata merged into LIV25 (read)         |


**Inside `SP26 Output`**


| Worksheet name | Used for                                            |
| -------------- | --------------------------------------------------- |
| `SP26 Prelim`  | Main exam rows: statuses, times, rooms (read/write) |


### 5.3 Optional third spreadsheet (mock / legacy)

`process_course_list()` also writes to `**FA25 NEW MOCK**` → worksheet `**Sign Ups**`. If you run the full `runner()` without changing code, that workbook must exist and be shared with the same service account, **or** you should coordinate with the team to skip or repoint that write for your environment.

### 5.4 Verify access

1. Confirm the service account email appears under **Share** on both **SP26 Input** and **SP26 Output** (and **FA25 NEW MOCK** if you use it).
2. From the repo root with venv activated, run a short Python check (optional). **Windows:** `python`; **macOS / Linux:** `python3` if that is what you use outside the venv (inside an activated venv, `python` is usually fine):
  ```bash
   python -c "from utils.access_google_sheets import get_sheet_as_df; df = get_sheet_as_df('SP26 Input', 'AIM Data'); print(df.head() if df is not None else 'failed')"
  ```

If this prints data, Sheets auth and sharing are working.

---

## 6. Gurobi license and `gurobipy`

Room allocation uses `**utils/gurobi_solver.py**` (`gurobipy`). You need a valid **Gurobi license** on the machine (or network path) where you solve models.

### 6.1 Academic / Cornell-style setup (typical for students)

1. Create a free account at [Gurobi](https://www.gurobi.com/) if you do not have one.
2. Request an **academic license** through Gurobi’s academic program (requirements and approval flow are on their site; often a `.edu` email and/or university verification).
3. After approval, Gurobi provides a **license key** or instructions to generate a `**gurobi.lic`** file (exact steps change with their portal version—follow the email and portal buttons they give you).

### 6.2 Install the license file

Common patterns:

- Place `**gurobi.lic**` in the default search path Gurobi documents for your OS, **or**
- Set environment variable `**GRB_LICENSE_FILE`** to the **absolute path** of `gurobi.lic`.

**Windows — PowerShell (current session only):**

```powershell
$env:GRB_LICENSE_FILE = "C:\path\to\gurobi.lic"
```

**Windows — persist:** **Settings → System → About → Advanced system settings → Environment Variables**, then add a user or system variable `GRB_LICENSE_FILE` pointing to the file.

**macOS / Linux — bash or zsh (current session only):**

```bash
export GRB_LICENSE_FILE="/absolute/path/to/gurobi.lic"
```

**macOS / Linux — persist:** add the same `export` line to `~/.zshrc` (macOS default shell) or `~/.bashrc` / `~/.profile` (many Linux installs), then run `source ~/.zshrc` (or the file you edited) or open a new terminal.

**Tip:** on macOS/Linux you can store the license inside the repo **only if** that directory is private; `keys/` is gitignored but a colleague’s clone will not contain your local `gurobi.lic`. A home-directory path such as `$HOME/gurobi/gurobi.lic` is often clearer.

### 6.3 Confirm Gurobi from Python

With your venv activated:

```python
import gurobipy as gp
print(gp.gurobi.version())
```

If imports succeed and a trivial model builds, the license is visible to Python:

```python
import gurobipy as gp
m = gp.Model("test")
m.optimize()
```

### 6.4 Commercial / lab licenses

If you use a **named-user** or **compute server** license, follow Gurobi’s admin guide for that license type; you still need `GRB_LICENSE_FILE` or default path configuration so `gurobipy` can check out a token.

---

## 7. Run the full pipeline

From the **repository root**, with venv activated, credentials in `keys/`, Sheets shared, Gurobi licensed, and `timetables/student_timetable.json` present:

```bash
python runner.py
```

On **macOS / Linux**, if `python` is not on your PATH even with the venv active, use:

```bash
python3 runner.py
```

That invokes `Prelims().runner()`, which reads/writes the sheets described above and may write local CSVs (`result1.csv`, `rooms.csv`, `exams.csv`, `result.csv`) for debugging—these file patterns are in `.gitignore` where applicable.

---

## Quick checklist

- Python venv created and activated  
- `pip install pandas gspread oauth2client` (and `gurobipy` after license)  
- Service account JSON in `keys/`, path matches `_get_client()`  
- Sheets API + Drive API enabled; key downloaded  
- **SP26 Input** and **SP26 Output** shared with service account **Editor**; tab names match  
- **FA25 NEW MOCK** / **Sign Ups** shared or code adjusted  
- `gurobi.lic` installed or `GRB_LICENSE_FILE` set  
- `python runner.py` runs without auth or license errors

If anything fails, note the **first** error message (Sheets permission vs. Gurobi license vs. missing worksheet name); those three categories cover most setup issues.