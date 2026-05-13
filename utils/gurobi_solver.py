import pandas as pd
import gurobipy as gp
from gurobipy import GRB
from itertools import combinations


def _hhmm_to_minutes(t):
    """Convert an HHMM-format integer (e.g. 840 → 8h40m) to minutes since midnight."""
    t = int(t)
    return (t // 100) * 60 + (t % 100)


def allot_rooms(exams_df, rooms_df):
    """
    Assign exam students to room slots using a Gurobi ILP.

    Constraints enforced:
      C1  Each exam is assigned to at most one room slot.
      C2  A concurrent exam-group within a room slot cannot exceed
          the room's testing capacity.
      C3  At most 3 distinct Course_IDs per concurrent exam-group.
      C4  If any student in a concurrent exam-group carries the RD
          tag, that group may hold at most 20 students.
      C5  Students with the PRIV or CODS tag are placed alone within
          their concurrent exam-group; other non-overlapping groups
          in the same room slot are unaffected.
      C6  The room must open at least 15 minutes before the exam
          starts (hard minimum).  30-minute buffer is preferred and
          optimised for via the objective.
      C7  Two exams assigned to the same room slot must not have
          conflicting time windows: if their windows differ, there
          must be at least 15 minutes between the two exams (hard minimum); 
          30 minutes is preferred and optimised for via P2.

    Objective hierarchy (descending priority):
      P5  Maximise the number of exams assigned.
      P4  Minimise the number of room slots used.
      P3  Minimise the total number of (course, exam-group) pairings,
          i.e. concentrate each course into as few exams+rooms as possible.
      P2  Prefer 30-minute pre-exam buffer over 15-minute.
      P1  Prefer rooms with >= 15-minute post-exam buffer.
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
    #  Pre-compute compatibility                                         #
    #  Hard requirement: room opens >= 15 min before exam start.         #
    #  Preferred:        room opens >= 30 min before exam start.         #
    # ------------------------------------------------------------------ #
    compat = set()
    has_30_buffer = set()
    has_15_post_buffer = set()
    exam_to_rooms: dict[int, list[int]] = {i: [] for i in range(n_e)}
    room_to_exams: dict[int, list[int]] = {j: [] for j in range(n_r)}

    for i in range(n_e):
        e_date = exams.at[i, "Date"]
        e_ts_min = _hhmm_to_minutes(exams.at[i, "Time_Start"])
        e_te_min = _hhmm_to_minutes(exams.at[i, "Time_End"])
        for j in range(n_r):
            r_ts_min = _hhmm_to_minutes(rooms.at[j, "Time_Start"])
            r_te_min = _hhmm_to_minutes(rooms.at[j, "Time_End"])
            if (
                e_date == rooms.at[j, "Date"]
                and e_ts_min - 15 >= r_ts_min
                and e_te_min <= r_te_min
            ):
                compat.add((i, j))
                exam_to_rooms[i].append(j)
                room_to_exams[j].append(i)
                if e_ts_min - 30 >= r_ts_min:
                    has_30_buffer.add((i, j))
                if r_te_min >= e_te_min + 15:
                    has_15_post_buffer.add((i, j))

    courses = exams["Course_ID"].unique().tolist()
    course_exams = {
        c: set(exams.index[exams["Course_ID"] == c]) for c in courses
    }
    rd_indices = [i for i in range(n_e) if has_rd.iloc[i]]
    priv_indices = [i for i in range(n_e) if needs_private.iloc[i]]

    # ------------------------------------------------------------------ #
    #  Pre-compute inter-exam gaps within each room slot (for C8 / P2)   #
    #  gap < 15  → hard conflict (C8 blocks both in same room slot)      #
    #  15 ≤ gap < 30 → allowed but penalised (prefer 30-min gap, P2)    #
    # ------------------------------------------------------------------ #
    inter_15_blocked: set[tuple[int, int, int]] = set()  # (i1, i2, j)
    inter_only_15: set[tuple[int, int, int]] = set()     # (i1, i2, j)

    for j in range(n_r):
        for i1, i2 in combinations(room_to_exams[j], 2):
            ts1 = _hhmm_to_minutes(exams.at[i1, "Time_Start"])
            te1 = _hhmm_to_minutes(exams.at[i1, "Time_End"])
            ts2 = _hhmm_to_minutes(exams.at[i2, "Time_Start"])
            te2 = _hhmm_to_minutes(exams.at[i2, "Time_End"])
            if ts1 == ts2:
                continue  # concurrent: no restriction
            gap = max(ts2 - te1, ts1 - te2)
            if gap < 15:
                inter_15_blocked.add((i1, i2, j))
            elif gap < 30:
                inter_only_15.add((i1, i2, j))

    # ------------------------------------------------------------------ #
    #  Group exams in each room slot by exact time window               #
    # ------------------------------------------------------------------ #
    groups: dict[int, dict[int, list[int]]] = {j: {} for j in range(n_r)}
    for j in range(n_r):
        for i in room_to_exams[j]:
            key = _hhmm_to_minutes(exams.at[i, "Time_Start"])
            groups[j].setdefault(key, []).append(i)

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
    # z_g[c, j, ts] = 1 iff course c has ≥1 exam in room j starts at time ts
    z_g = {
        (c, j, ts): model.addVar(vtype=GRB.BINARY, name=f"zg_{c}_{j}_{ts}")
        for j in range(n_r)
        for ts in groups[j]
        for c in courses
        if any(exams.at[i, "Course_ID"] == c for i in groups[j][ts])
    }
    # rd_flag_g[j, ts] = 1 iff the concurrent group (j, ts) contains an RD exam
    rd_flag_g = {
        (j, ts): model.addVar(vtype=GRB.BINARY, name=f"rfg_{j}_{ts}")
        for j in range(n_r)
        for ts in groups[j]
    }
    # q[i1,i2,j] = 1 iff both i1 and i2 are assigned to room j with only a
    # 15-min inter-exam gap (< 30 min); used to penalise tight scheduling (P2).
    q = {
        (i1, i2, j): model.addVar(vtype=GRB.BINARY, name=f"q_{i1}_{i2}_{j}")
        for (i1, i2, j) in inter_only_15
    }

    model.update()

    # ------------------------------------------------------------------ #
    #  Multi-objective  (all minimised; negate to maximise assignments)   #
    # ------------------------------------------------------------------ #
    model.ModelSense = GRB.MINIMIZE

    model.setObjectiveN(
        -gp.quicksum(x[i, j] for (i, j) in compat),
        index=0, priority=5, weight=1.0, name="max_assign",
    )
    model.setObjectiveN(
        gp.quicksum(y[j] for j in range(n_r)),
        index=1, priority=4, weight=1.0, name="min_rooms",
    )
    model.setObjectiveN(
        gp.quicksum(z_g[c, j, ts] for (c, j, ts) in z_g),
        index=2, priority=3, weight=1.0, name="min_rooms_per_course",
    )
    only_15 = compat - has_30_buffer
    model.setObjectiveN(
        gp.quicksum(x[i, j] for (i, j) in only_15)
        + gp.quicksum(q[i1, i2, j] for (i1, i2, j) in inter_only_15),
        index=3, priority=2, weight=1.0, name="prefer_30_buffer",
    )
    no_post_buffer = compat - has_15_post_buffer
    model.setObjectiveN(
        gp.quicksum(x[i, j] for (i, j) in no_post_buffer),
        index=4, priority=1, weight=1.0, name="prefer_15_post",
    )
    zone2_slots = {j for j in range(n_r) if rooms.at[j, "Zone"] != 1.0}
    model.setObjectiveN(
        gp.quicksum(x[i, j] for (i, j) in compat if j in zone2_slots),
        index=5, priority=0, weight=1.0, name="prefer_zone1",
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

    # C2 – capacity per concurrent exam-group
    for j in range(n_r):
        cap = int(rooms.at[j, "Testing capacity"])
        for ts, group in groups[j].items():
            model.addConstr(
                gp.quicksum(x[i, j] for i in group) <= cap,
                name=f"cap_{j}_{ts}",
            )

    # C3 – at most 3 distinct courses per concurrent exam-group
    for j in range(n_r):
        for ts, group in groups[j].items():
            for c in courses:
                ce = [i for i in group if i in course_exams[c]]
                for i in ce:
                    model.addConstr(
                        z_g[c, j, ts] >= x[i, j],
                        name=f"zgl_{c}_{j}_{ts}_{i}",
                    )
                if ce:
                    model.addConstr(
                        z_g[c, j, ts] <= gp.quicksum(x[i, j] for i in ce),
                        name=f"zgu_{c}_{j}_{ts}",
                    )
            model.addConstr(
                gp.quicksum(
                    z_g[c, j, ts] for c in courses if (c, j, ts) in z_g
                ) <= 3,
                name=f"max3_{j}_{ts}",
            )

    # C4 – RD tag  →  concurrent exam-group capped at 20 students
    for j in range(n_r):
        cap = int(rooms.at[j, "Testing capacity"])
        for ts, group in groups[j].items():
            rd_here = [i for i in group if i in rd_indices]
            for i in rd_here:
                model.addConstr(
                    rd_flag_g[j, ts] >= x[i, j],
                    name=f"rdl_{j}_{ts}_{i}",
                )
            if group and cap > 20:
                model.addConstr(
                    gp.quicksum(x[i, j] for i in group)
                    <= cap - (cap - 20) * rd_flag_g[j, ts],
                    name=f"rdc_{j}_{ts}",
                )

    # C5 – PRIV / CODS  →  student must be alone in their concurrent exam-group
    for i in priv_indices:
        ts_i = _hhmm_to_minutes(exams.at[i, "Time_Start"])
        for j in exam_to_rooms[i]:
            same_group = [
                k for k in groups[j].get(ts_i, []) if k != i
            ]
            if same_group:
                model.addConstr(
                    gp.quicksum(x[k, j] for k in same_group)
                    <= int(rooms.at[j, "Testing capacity"]) * (1 - x[i, j]),
                    name=f"priv_{i}_{j}",
                )

    # C7 – non-overlapping exams in the same room slot
    # Hard: block pairs whose inter-exam gap < 15 min
    for (i1, i2, j) in inter_15_blocked:
        model.addConstr(
            x[i1, j] + x[i2, j] <= 1,
            name=f"nooverlap_{i1}_{i2}_{j}",
        )
    # Link q to x: q=1 iff both exams are assigned to the same room with only 15-min gap
    for (i1, i2, j) in inter_only_15:
        model.addConstr(
            q[i1, i2, j] >= x[i1, j] + x[i2, j] - 1,
            name=f"ql_{i1}_{i2}_{j}",
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
                    f"  {rooms.at[j, 'slot_id']}  "
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
