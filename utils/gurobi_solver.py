import pandas as pd
import gurobipy as gp
from gurobipy import GRB
from itertools import combinations


def allot_rooms(exams_df, rooms_df):
    """
    Assign exam students to room slots using a Gurobi ILP.

    Constraints enforced:
      C1  Each exam is assigned to at most one room slot.
      C2  A room slot cannot exceed its testing capacity.
      C3  At most 3 distinct Course_IDs per room slot.
      C4  If any student in a room carries the RD tag, that room
          may hold at most 20 students.
      C5  Students with the PRIV or CODS tag are placed alone.
      C6  Overlapping time slots for the same physical room on the
          same date share a single capacity limit.

    Objective hierarchy (descending priority):
      P2  Maximise the number of exams assigned.
      P1  Minimise the number of room slots used.
      P0  Prefer Zone-1 rooms over Zone-2.

    Returns the exams DataFrame with 'Room No' and 'Internal Status'
    columns updated for every successfully assigned exam.
    """

    # ------------------------------------------------------------------ #
    #  Prepare rooms – drop slots without a usable capacity              #
    # ------------------------------------------------------------------ #
    rooms = rooms_df.dropna(subset=["Testing capacity"]).copy()
    rooms = rooms[rooms["Testing capacity"] > 0].reset_index(drop=True)
    rooms["Testing capacity"] = rooms["Testing capacity"].astype(int)
    rooms["Zone"] = rooms["Zone"].fillna(2).astype(float)
    rooms["Date"] = rooms["Date"].astype(str).str.strip()
    rooms["Time_Start"] = pd.to_numeric(rooms["Time_Start"])
    rooms["Time_End"] = pd.to_numeric(rooms["Time_End"])

    # ------------------------------------------------------------------ #
    #  Prepare exams                                                     #
    # ------------------------------------------------------------------ #
    exams = exams_df.copy().reset_index(drop=True)
    exams["Date"] = exams["Date"].astype(str).str.strip()
    exams["Time_Start"] = pd.to_numeric(exams["Time_Start"])
    exams["Time_End"] = pd.to_numeric(exams["Time_End"])

    tags_parsed = (
        exams["Tags"]
        .fillna("")
        .astype(str)
        .apply(lambda t: {s.strip() for s in t.split("|") if s.strip()})
    )
    has_rd = tags_parsed.apply(lambda s: "RD" in s)
    needs_private = tags_parsed.apply(lambda s: bool(s & {"PRIV", "CODS"}))

    n_e, n_r = len(exams), len(rooms)

    # ------------------------------------------------------------------ #
    #  Pre-compute compatibility  (exam i fits inside room slot j)       #
    # ------------------------------------------------------------------ #
    compat = set()
    exam_to_rooms: dict[int, list[int]] = {i: [] for i in range(n_e)}
    room_to_exams: dict[int, list[int]] = {j: [] for j in range(n_r)}

    for i in range(n_e):
        e_date = exams.at[i, "Date"]
        e_ts = exams.at[i, "Time_Start"]
        e_te = exams.at[i, "Time_End"]
        for j in range(n_r):
            if (
                e_date == rooms.at[j, "Date"]
                and e_ts >= rooms.at[j, "Time_Start"]
                and e_te <= rooms.at[j, "Time_End"]
            ):
                compat.add((i, j))
                exam_to_rooms[i].append(j)
                room_to_exams[j].append(i)

    courses = exams["Course_ID"].unique().tolist()
    course_exams = {
        c: exams.index[exams["Course_ID"] == c].tolist() for c in courses
    }
    rd_indices = [i for i in range(n_e) if has_rd.iloc[i]]
    priv_indices = [i for i in range(n_e) if needs_private.iloc[i]]

    # ------------------------------------------------------------------ #
    #  Build Gurobi model                                                #
    # ------------------------------------------------------------------ #
    model = gp.Model("room_allocation")
    model.Params.OutputFlag = 1

    x = {
        (i, j): model.addVar(vtype=GRB.BINARY, name=f"x_{i}_{j}")
        for (i, j) in compat
    }
    y = {
        j: model.addVar(vtype=GRB.BINARY, name=f"y_{j}")
        for j in range(n_r)
    }
    z = {
        (c, j): model.addVar(vtype=GRB.BINARY, name=f"z_{c}_{j}")
        for c in courses
        for j in range(n_r)
    }
    rd_flag = {
        j: model.addVar(vtype=GRB.BINARY, name=f"rf_{j}")
        for j in range(n_r)
    }

    model.update()

    # ------------------------------------------------------------------ #
    #  Multi-objective  (all minimised; negate to maximise assignments)   #
    # ------------------------------------------------------------------ #
    model.ModelSense = GRB.MINIMIZE

    model.setObjectiveN(
        -gp.quicksum(x[i, j] for (i, j) in compat),
        index=0, priority=2, weight=1.0, name="max_assign",
    )
    model.setObjectiveN(
        gp.quicksum(y[j] for j in range(n_r)),
        index=1, priority=1, weight=1.0, name="min_rooms",
    )
    zone2_slots = {j for j in range(n_r) if rooms.at[j, "Zone"] != 1.0}
    model.setObjectiveN(
        gp.quicksum(x[i, j] for (i, j) in compat if j in zone2_slots),
        index=2, priority=0, weight=1.0, name="prefer_zone1",
    )

    # ------------------------------------------------------------------ #
    #  Constraints                                                       #
    # ------------------------------------------------------------------ #

    # C1 – each exam goes to at most one room
    for i in range(n_e):
        if exam_to_rooms[i]:
            model.addConstr(
                gp.quicksum(x[i, j] for j in exam_to_rooms[i]) <= 1,
                name=f"assign_{i}",
            )

    # Link room-usage indicator
    for j in range(n_r):
        for i in room_to_exams[j]:
            model.addConstr(x[i, j] <= y[j], name=f"link_{i}_{j}")

    # C2 – room capacity
    for j in range(n_r):
        cap = int(rooms.at[j, "Testing capacity"])
        if room_to_exams[j]:
            model.addConstr(
                gp.quicksum(x[i, j] for i in room_to_exams[j]) <= cap,
                name=f"cap_{j}",
            )

    # C3 – at most 3 distinct courses per room
    for c in courses:
        for j in range(n_r):
            ce = [i for i in course_exams[c] if (i, j) in compat]
            for i in ce:
                model.addConstr(z[c, j] >= x[i, j], name=f"zl_{c}_{j}_{i}")
            if ce:
                model.addConstr(
                    z[c, j] <= gp.quicksum(x[i, j] for i in ce),
                    name=f"zu_{c}_{j}",
                )

    for j in range(n_r):
        model.addConstr(
            gp.quicksum(z[c, j] for c in courses) <= 3,
            name=f"max3_{j}",
        )

    # C4 – RD tag  →  room capped at 20 students
    for j in range(n_r):
        cap = int(rooms.at[j, "Testing capacity"])
        rd_here = [i for i in rd_indices if (i, j) in compat]
        for i in rd_here:
            model.addConstr(rd_flag[j] >= x[i, j], name=f"rdl_{j}_{i}")
        if room_to_exams[j] and cap > 20:
            model.addConstr(
                gp.quicksum(x[i, j] for i in room_to_exams[j])
                <= cap - (cap - 20) * rd_flag[j],
                name=f"rdc_{j}",
            )

    # C5 – PRIV / CODS  →  student must be alone in the room
    for i in priv_indices:
        for j in exam_to_rooms[i]:
            others = [k for k in room_to_exams[j] if k != i]
            if others:
                model.addConstr(
                    gp.quicksum(x[k, j] for k in others)
                    <= int(rooms.at[j, "Testing capacity"]) * (1 - x[i, j]),
                    name=f"priv_{i}_{j}",
                )

    # C6 – overlapping time slots for the same physical room share capacity
    room_date_slots: dict[tuple, list[int]] = {}
    for j in range(n_r):
        key = (rooms.at[j, "Location_Name"], rooms.at[j, "Date"])
        room_date_slots.setdefault(key, []).append(j)

    for (loc, dt), slot_list in room_date_slots.items():
        if len(slot_list) <= 1:
            continue
        cap = int(rooms.at[slot_list[0], "Testing capacity"])
        for j1, j2 in combinations(slot_list, 2):
            ts1, te1 = rooms.at[j1, "Time_Start"], rooms.at[j1, "Time_End"]
            ts2, te2 = rooms.at[j2, "Time_Start"], rooms.at[j2, "Time_End"]
            if ts1 < te2 and ts2 < te1:
                pairs = [
                    (i, j) for j in (j1, j2)
                    for i in room_to_exams[j]
                    if (i, j) in compat
                ]
                if pairs:
                    model.addConstr(
                        gp.quicksum(x[i, j] for (i, j) in pairs) <= cap,
                        name=f"overlap_{loc}_{dt}_{j1}_{j2}",
                    )

    # ------------------------------------------------------------------ #
    #  Solve                                                             #
    # ------------------------------------------------------------------ #
    model.optimize()

    assigned = 0
    if model.SolCount > 0:
        for (i, j) in compat:
            if x[i, j].X > 0.5:
                exams.at[i, "Room No"] = rooms.at[j, "Location_Name"]
                exams.at[i, "Internal Status"] = "Room allocated"
                assigned += 1

        rooms_used = sum(1 for j in range(n_r) if y[j].X > 0.5)
        print(f"\n{'=' * 45}")
        print(f"  Room Allocation Results")
        print(f"{'=' * 45}")
        print(f"  Exams assigned : {assigned} / {n_e}")
        print(f"  Rooms used     : {rooms_used}")
        print(f"{'=' * 45}")

        for j in range(n_r):
            if y[j].X > 0.5:
                assigned_here = [
                    i for i in room_to_exams[j]
                    if (i, j) in compat and x[i, j].X > 0.5
                ]
                course_set = {exams.at[i, "Course_ID"] for i in assigned_here}
                print(
                    f"  {rooms.at[j, 'Location_Name']:>8s}  "
                    f"{rooms.at[j, 'Date']}  "
                    f"{int(rooms.at[j, 'Time_Start']):04d}-{int(rooms.at[j, 'Time_End']):04d}  "
                    f"Zone {int(rooms.at[j, 'Zone'])}  |  "
                    f"{len(assigned_here)} student(s), "
                    f"{len(course_set)} course(s)"
                )
        print()

        unassigned = exams[exams["Internal Status"] != "Room allocated"]
        if len(unassigned) > 0:
            print(f"  Unassigned exams ({len(unassigned)}):")
            for _, row in unassigned.iterrows():
                print(
                    f"    Exam {row['Exam_ID']}  Student {row['Student_ID']}  "
                    f"Course {row['Course_ID']}  "
                    f"{row['Date']} {int(row['Time_Start']):04d}-{int(row['Time_End']):04d}"
                )
            print()
    else:
        print("No feasible solution found.")

    return exams
