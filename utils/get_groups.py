import pandas as pd
from itertools import combinations

def assign_groups(exams_df):
    """
    Assigns a group_id to each row in exams_df based on:
      - Primary grouping: Date + Course_ID + Time_Start
      - PRIV tag: student gets a solo group
      - CODS tag: student gets a solo group
      - RD tag: if the non-PRIV/non-CODS pool for a base group is >= 20,
                RD students are split into their own subgroup
      - Small groups (1-2 students, no PRIV/CODS) on the same Date+Time_Start
        are merged together to minimise rooms

    Returns exams_df with a new 'group_id' column (integer).
    """

    def parse_tags(tags_val):
        if pd.isna(tags_val) or str(tags_val).strip() == "":
            return set()
        return {t.strip().upper() for t in str(tags_val).split("|")}

    # Work on a copy; we'll write group_id back at the end
    df = exams_df.copy()
    df["_tags"] = df["Tags"].apply(parse_tags)

    group_counter = 1
    # Maps row index → group_id
    group_map = {}

    # ── Step 1: form initial groups by (Date, Course_ID, Time_Start) ─────────
    base_groups = df.groupby(["Date", "Course_ID", "Time_Start"], sort=False)

    # Each entry: {"indices": [...], "is_special": bool}
    # is_special = True means PRIV or CODS (must never be merged)
    formed_groups = []   # list of dicts

    for (grp_date, grp_course, grp_time), grp_df in base_groups:

        # Classify each student in the base group
        priv_cods_idx = []   # PRIV or CODS — always solo
        rd_idx        = []   # RD only (not PRIV/CODS)
        regular_idx   = []   # no special tag

        for idx, row in grp_df.iterrows():
            tags = row["_tags"]
            if "PRIV" in tags or "CODS" in tags:
                priv_cods_idx.append(idx)
            elif "RD" in tags:
                rd_idx.append(idx)
            else:
                regular_idx.append(idx)

        # Total non-PRIV/non-CODS students decides whether RD gets split
        non_special_total = len(rd_idx) + len(regular_idx)
        rd_gets_own_group = non_special_total >= 20

        # ── PRIV / CODS → one solo group each ────────────────────────────────
        for idx in priv_cods_idx:
            formed_groups.append({
                "indices":    [idx],
                "is_special": True,   # never merge
                "date":       grp_date,
                "time":       grp_time,
            })

        # ── RD students ───────────────────────────────────────────────────────
        if rd_gets_own_group:
            # Split into their own group (all RD together, not solo)
            if rd_idx:
                formed_groups.append({
                    "indices":    rd_idx,
                    "is_special": False,  # large enough — no merge needed
                    "date":       grp_date,
                    "time":       grp_time,
                })
        else:
            # RD folds back into regular pool (group is small)
            regular_idx = regular_idx + rd_idx

        # ── Regular (+ possibly RD) students → one group ─────────────────────
        if regular_idx:
            formed_groups.append({
                "indices":    regular_idx,
                "is_special": False,
                "date":       grp_date,
                "time":       grp_time,
            })

    # ── Step 2: merge small non-special groups on same Date + Time_Start ─────
    # "Small" = 1 or 2 students
    # Strategy: collect all small mergeable groups per (date, time),
    # then greedily pack them together. We do NOT break up groups that
    # are already ≥ 3; we only merge groups that are individually small.

    from collections import defaultdict

    # Bucket by (date, time)
    slot_buckets = defaultdict(list)   # (date, time) → list of group dicts
    final_groups_special = []          # special groups bypass merging

    for g in formed_groups:
        if g["is_special"]:
            final_groups_special.append(g)
        else:
            slot_buckets[(g["date"], g["time"])].append(g)

    final_groups = list(final_groups_special)

    for (slot_date, slot_time), groups_in_slot in slot_buckets.items():
        small  = [g for g in groups_in_slot if len(g["indices"]) <= 2]
        normal = [g for g in groups_in_slot if len(g["indices"]) > 2]

        # Keep normal groups as-is
        final_groups.extend(normal)

        # Merge small groups greedily into buckets
        merged_indices = []
        for g in small:
            merged_indices.extend(g["indices"])

        if merged_indices:
            # Treat the merged blob as a single group
            final_groups.append({
                "indices":    merged_indices,
                "is_special": False,
                "date":       slot_date,
                "time":       slot_time,
            })

    # ── Step 3: assign sequential group IDs ──────────────────────────────────
    for g in final_groups:
        for idx in g["indices"]:
            group_map[idx] = group_counter
        group_counter += 1

    exams_df = exams_df.copy()
    exams_df["group_id"] = exams_df.index.map(group_map)
    return exams_df