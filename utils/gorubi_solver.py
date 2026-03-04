import gurobipy as gp
from gurobipy import GRB
import math
import pandas as pd


def assign_rooms(groups_df, rooms_df):
    """
    Assigns exam groups to room slots.

    groups_df columns: group_id, Group_size, Date, Time_Start, Time_End, Tags
    rooms_df  columns: slot_id, Location Name, Date, Time_Start, Time_End, Max_Cap

    Rules:
    - A slot can host multiple groups as long as their exam times don't overlap.
    - Each group's students in a slot must not exceed 50% of slot capacity.
    - Prefer matching larger groups to larger rooms.

    Returns a DataFrame: group_id, slot_id, Location Name,
                         students_count, Max_Cap, cap_50pct
    """
    
    groups = groups_df.to_dict(orient="records")
    rooms  = rooms_df.to_dict(orient="records")

    G     = [g["group_id"] for g in groups]
    R     = [r["slot_id"]  for r in rooms]
    gdata = {g["group_id"]: g for g in groups}
    rdata = {r["slot_id"]:  r for r in rooms}

    # 50% capacity limit per slot
    cap = {r["slot_id"]: math.floor(r["Max_Cap"] * 0.5) for r in rooms}

    def slot_covers_group(room, group):
        """Slot's date+time window fully covers the group's exam window."""
        return room["Date"] == group["Date"] and int(room["Time_Start"]) <= int(group["Time_Start"]) and int(room["Time_End"]) >= int(group["Time_End"])

    def exams_overlap(g1, g2):
        """True if two groups have overlapping exam times on the same date."""
        return g1["Date"] == g2["Date"] and int(g1["Time_Start"]) < int(g2["Time_End"]) and int(g2["Time_Start"]) < int(g1["Time_End"])

    # Compatible (group, slot) pairs
    compat = {
        (g, r): slot_covers_group(rdata[r], gdata[g])
        for g in G for r in R
    }

    # Pairs of groups whose exam times overlap
    conflict = {}
    for i, g1 in enumerate(G):
        for g2 in G[i + 1:]:
            conflict[g1, g2] = exams_overlap(gdata[g1], gdata[g2])


    # ── Model ─────────────────────────────────────────────────────────────────
    m = gp.Model("exam_scheduling")
    m.Params.OutputFlag = 0   # set to 1 to see solver log

    # r2g[g, r] = 1  →  slot r is used for (part of) group g
    r2g = m.addVars(G, R, vtype=GRB.BINARY, name="r2g")

    # g2r[g, r] = number of students from group g placed in slot r
    g2r = m.addVars(G, R, vtype=GRB.INTEGER, lb=0, name="g2r")

    # ── Constraints ───────────────────────────────────────────────────────────

    # 1. Block incompatible (group, slot) pairs
    for g in G:
        for r in R:
            if not compat[g, r]:
                m.addConstr(r2g[g, r] == 0, name=f"incompat_{g}_{r}")

    # 2. All students must be assigned
    for g in G:
        m.addConstr(
            gp.quicksum(g2r[g, r] for r in R) == gdata[g]["Group_size"],
            name=f"coverage_{g}"
        )

    # 3. Enforce 50% cap per slot; link g2r to r2g
    for g in G:
        for r in R:
            m.addConstr(g2r[g, r] <= cap[r] * r2g[g, r], name=f"cap_{g}_{r}")
            m.addConstr(g2r[g, r] >= r2g[g, r],          name=f"atleast1_{g}_{r}")

    # 4. No two time-overlapping groups can share the same slot
    for r in R:
        for (g1, g2), is_conflict in conflict.items():
            if is_conflict:
                m.addConstr(r2g[g1, r] + r2g[g2, r] <= 1, name=f"noconflict_{g1}_{g2}_{r}")

    # ── Objective ─────────────────────────────────────────────────────────────
    # Primary:   minimize total slot assignments (compact packing)
    # Secondary: prefer large groups in large rooms (tiebreaker)
    slots_used = gp.quicksum(r2g[g, r] for g in G for r in R)
    size_match = gp.quicksum(
        g2r[g, r] * rdata[r]["Max_Cap"]
        for g in G for r in R
    )
    max_size = max(g["Group_size"] for g in groups)
    max_cap  = max(r["Max_Cap"] for r in rooms)

    m.setObjective(
        slots_used - (0.01 / (max_size * max_cap)) * size_match,
        GRB.MINIMIZE
    )

    # ── Solve ─────────────────────────────────────────────────────────────────
    m.Params.MIPGap    = 0.0
    m.Params.TimeLimit = 120

    m.optimize()

    # ── Results ────────────────────────────────────────────────────────
    if m.status == GRB.INFEASIBLE:
        m.computeIIS()
        m.write("infeasible.ilp")
        raise RuntimeError("assign_rooms: INFEASIBLE — see infeasible.ilp")

    if m.status not in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        raise RuntimeError(f"assign_rooms: unexpected solver status {m.status}")

    results = []
    for g in sorted(G, key=lambda g: -gdata[g]["Group_size"]):
        for r in R:
            if r2g[g, r].X > 0.5:
                results.append({
                    "group_id":          g,
                    "slot_id":           r,
                    "Location Name":     rdata[r]["Location Name"],
                    "students_count": int(round(g2r[g, r].X)),
                    "Max_Cap":      rdata[r]["Max_Cap"],
                    "cap_50pct":         cap[r],
                })

    return pd.DataFrame(results)
