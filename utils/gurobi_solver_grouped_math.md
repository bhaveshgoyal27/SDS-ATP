# Mathematical Formulation — `gurobi_solver_grouped.py`

This document states the full Integer Linear Program (ILP) solved by
`allot_rooms` in `utils/gurobi_solver_grouped.py`: sets, parameters,
decision variables, constraints, and the lexicographic multi-objective.

---

## 1. Sets and indices

| Symbol | Meaning |
|---|---|
| \(E = \{1,\ldots,n_e\}\) | Student exam-rows (one row = one student sitting one exam) |
| \(R = \{1,\ldots,n_r\}\) | Room availability slots (rows with positive testing capacity) |
| \(C\) | Distinct course IDs appearing in \(E\) |
| \(G\) | Exam **cohorts**: students with the same \((\mathrm{Course\_ID},\mathrm{Date},\mathrm{Time\_Start},\mathrm{Time\_End})\) |
| \(E_g \subseteq E\) | Student rows belonging to cohort \(g \in G\) |
| \(C_c \subseteq E\) | Student rows with course \(c \in C\) |
| \(E^{\mathrm{RD}} \subseteq E\) | Rows tagged `RD` |
| \(E^{\mathrm{PRIV}} \subseteq E\) | Rows tagged `PRIV` or `CODS` |

### Compatibility and time structure

| Symbol | Meaning |
|---|---|
| \(\mathcal{A} \subseteq E \times R\) | Compatible pairs \((i,j)\): same date, exam fits in room window, and room opens \(\ge 15\) min before exam start |
| \(R_i = \{j : (i,j)\in\mathcal{A}\}\) | Rooms compatible with exam \(i\) |
| \(E_j = \{i : (i,j)\in\mathcal{A}\}\) | Exams compatible with room \(j\) |
| \(R_g = \bigcup_{i\in E_g} R_i\) | Rooms compatible with at least one member of cohort \(g\) |
| \(T_j\) | Distinct exam start times (minutes) among exams in \(E_j\) |
| \(E_{j,t} \subseteq E_j\) | Concurrent group: exams in slot \(j\) with start time \(t\) |
| \(\mathcal{B}_{30} \subseteq \mathcal{A}\) | Pairs with \(\ge 30\) min pre-exam open buffer |
| \(\mathcal{B}^{\mathrm{post}}_{15} \subseteq \mathcal{A}\) | Pairs with \(\ge 15\) min post-exam buffer before room close |
| \(\mathcal{A}_{15} = \mathcal{A}\setminus\mathcal{B}_{30}\) | Compatible pairs with only a 15–29 min pre-buffer |
| \(\mathcal{A}^{\mathrm{post}}_0 = \mathcal{A}\setminus\mathcal{B}^{\mathrm{post}}_{15}\) | Compatible pairs lacking a 15 min post-buffer |
| \(R^{Z2} \subseteq R\) | Room slots with Zone \(\neq 1\) |
| \(\mathcal{F}_{15} \subseteq E\times E\times R\) | Non-concurrent pairs in slot \(j\) with inter-exam gap \(< 15\) min (hard conflict) |
| \(\mathcal{F}_{15\text{–}29} \subseteq E\times E\times R\) | Non-concurrent pairs in slot \(j\) with gap in \([15,30)\) min (soft penalty) |

For non-concurrent \(i_1,i_2\) in the same slot \(j\), the gap is
\[
\mathrm{gap}(i_1,i_2)
=
\max\bigl(t^{\mathrm{start}}_{i_2}-t^{\mathrm{end}}_{i_1},\;
t^{\mathrm{start}}_{i_1}-t^{\mathrm{end}}_{i_2}\bigr).
\]
Same start time \(\Rightarrow\) concurrent (no gap rule).

### Room and exam parameters

| Symbol | Meaning |
|---|---|
| \(\mathrm{cap}_j \in \mathbb{Z}_{>0}\) | Testing capacity of room slot \(j\) |
| \(t^{\mathrm{start}}_i,\; t^{\mathrm{end}}_i\) | Exam start/end (minutes since midnight) |
| \(r^{\mathrm{open}}_j,\; r^{\mathrm{close}}_j\) | Room slot open/close (minutes) |

**Compatibility (C6, enforced by restricting \(\mathcal{A}\)):**
\[
(i,j)\in\mathcal{A}
\iff
\mathrm{date}_i=\mathrm{date}_j
\;\wedge\;
t^{\mathrm{start}}_i - 15 \ge r^{\mathrm{open}}_j
\;\wedge\;
t^{\mathrm{end}}_i \le r^{\mathrm{close}}_j.
\]

---

## 2. Decision variables

All variables are binary.

| Variable | Domain | Meaning |
|---|---|---|
| \(x_{ij}\) | \((i,j)\in\mathcal{A}\) | \(1\) if exam-row \(i\) is assigned to room slot \(j\) |
| \(y_j\) | \(j\in R\) | \(1\) if room slot \(j\) is used by any assigned exam |
| \(u_{gj}\) | \(g\in G,\; j\in R_g\) | \(1\) if cohort \(g\) places **at least one** student in room \(j\) |
| \(z_{cjt}\) | \(c\in C,\; j\in R,\; t\in T_j\) (when course \(c\) appears among candidates in \(E_{j,t}\)) | \(1\) if course \(c\) has \(\ge 1\) assigned student in concurrent group \((j,t)\) |
| \(\rho_{jt}\) | \(j\in R,\; t\in T_j\) | \(1\) if concurrent group \((j,t)\) contains an assigned RD student |
| \(q_{i_1 i_2 j}\) | \((i_1,i_2,j)\in\mathcal{F}_{15\text{–}29}\) | \(1\) if both \(i_1\) and \(i_2\) are assigned to \(j\) with only a 15–29 min gap |

\[
x_{ij},\; y_j,\; u_{gj},\; z_{cjt},\; \rho_{jt},\; q_{i_1 i_2 j}
\;\in\;
\{0,1\}.
\]

---

## 3. Constraints

### C1 — At most one room per exam

\[
\sum_{j \in R_i} x_{ij} \;\le\; 1
\qquad \forall\, i\in E \text{ with } R_i\neq\emptyset.
\]

### Link \(y\) — Room usage

\[
x_{ij} \;\le\; y_j
\qquad \forall\, (i,j)\in\mathcal{A}.
\]

### Link \(u\) — Cohort–room indicator

For each \(g\in G\), \(j\in R_g\), let \(E_g(j)=\{i\in E_g:(i,j)\in\mathcal{A}\}\).

\[
\begin{aligned}
u_{gj} &\ge x_{ij}
&& \forall\, i\in E_g(j), \\[4pt]
u_{gj} &\le \sum_{i\in E_g(j)} x_{ij}
&& \text{(if } E_g(j)\neq\emptyset\text{)}.
\end{aligned}
\]

So \(u_{gj}=1\) iff at least one member of cohort \(g\) is assigned to \(j\).

### C2 — Capacity per concurrent group

\[
\sum_{i \in E_{j,t}} x_{ij} \;\le\; \mathrm{cap}_j
\qquad \forall\, j\in R,\; t\in T_j.
\]

### C3 — At most three courses per concurrent group

Linking for course indicators (standard big-\(M\) / indicator bounds):

\[
\begin{aligned}
z_{cjt} &\ge x_{ij}
&& \forall\, i\in E_{j,t}\cap C_c, \\[4pt]
z_{cjt} &\le \sum_{i\in E_{j,t}\cap C_c} x_{ij}
&& \text{(when } E_{j,t}\cap C_c\neq\emptyset\text{)}, \\[6pt]
\sum_{\substack{c\in C\\ z_{cjt}\text{ defined}}} z_{cjt} &\le 3
&& \forall\, j\in R,\; t\in T_j.
\end{aligned}
\]

### C4 — RD tag \(\Rightarrow\) concurrent group capped at 20

If \(\mathrm{cap}_j > 20\) and \(E_{j,t}\neq\emptyset\):

\[
\begin{aligned}
\rho_{jt} &\ge x_{ij}
&& \forall\, i\in E_{j,t}\cap E^{\mathrm{RD}}, \\[6pt]
\sum_{i\in E_{j,t}} x_{ij}
&\le
\mathrm{cap}_j - (\mathrm{cap}_j - 20)\,\rho_{jt}.
\end{aligned}
\]

When \(\rho_{jt}=0\), the right-hand side is \(\mathrm{cap}_j\); when \(\rho_{jt}=1\), it becomes \(20\).

### C5 — PRIV / CODS alone in concurrent group

For each \(i\in E^{\mathrm{PRIV}}\), let \(t_i=t^{\mathrm{start}}_i\) and
\(E_{j,t_i}^{(-i)}=E_{j,t_i}\setminus\{i\}\).

\[
\sum_{k\in E_{j,t_i}^{(-i)}} x_{kj}
\;\le\;
\mathrm{cap}_j\,(1 - x_{ij})
\qquad \forall\, j\in R_i \text{ with } E_{j,t_i}^{(-i)}\neq\emptyset.
\]

If \(x_{ij}=1\), no other exam may share concurrent group \((j,t_i)\).

### C7 — Inter-exam spacing (hard)

\[
x_{i_1 j} + x_{i_2 j} \;\le\; 1
\qquad \forall\, (i_1,i_2,j)\in\mathcal{F}_{15}.
\]

### Soft-gap linking for \(q\) (used in P2)

\[
q_{i_1 i_2 j}
\;\ge\;
x_{i_1 j} + x_{i_2 j} - 1
\qquad \forall\, (i_1,i_2,j)\in\mathcal{F}_{15\text{–}29}.
\]

(Minimizing \(\sum q\) in P2 forces \(q=1\) only when both exams are assigned with a tight 15–29 min gap.)

---

## 4. Multi-objective (lexicographic)

Gurobi `setObjectiveN` with **minimize** sense. Higher priority is optimized first; later priorities are optimized without worsening earlier ones.

\[
\begin{aligned}
\textbf{(P5)}\quad
&\min\;
-\sum_{(i,j)\in\mathcal{A}} x_{ij}
&&\text{(maximize assignments)} \\[8pt]
\textbf{(P4)}\quad
&\min\;
\sum_{g\in G}\;\sum_{j\in R_g} u_{gj}
&&\text{(minimize rooms per cohort / avoid splits)} \\[8pt]
\textbf{(P3)}\quad
&\min\;
\sum_{j\in R} y_j
&&\text{(minimize total room slots used)} \\[8pt]
\textbf{(P2)}\quad
&\min\;
\sum_{(i,j)\in\mathcal{A}_{15}} x_{ij}
\;+\;
\sum_{(i_1,i_2,j)\in\mathcal{F}_{15\text{–}29}} q_{i_1 i_2 j}
&&\text{(prefer 30 min pre-/inter-exam buffers)} \\[8pt]
\textbf{(P1)}\quad
&\min\;
\sum_{(i,j)\in\mathcal{A}^{\mathrm{post}}_0} x_{ij}
&&\text{(prefer 15 min post-exam buffer)} \\[8pt]
\textbf{(P0)}\quad
&\min\;
\sum_{\substack{(i,j)\in\mathcal{A}\\ j\in R^{Z2}}} x_{ij}
&&\text{(prefer Zone 1 over Zone 2)}.
\end{aligned}
\]

Priority order in code: P5 \(>\) P4 \(>\) P3 \(>\) P2 \(>\) P1 \(>\) P0
(priorities \(5,4,3,2,1,0\)).

---

## 5. Compact statement of the model

\[
\begin{aligned}
\text{lex-min}\quad
&\Bigl(
-\textstyle\sum_{(i,j)\in\mathcal{A}} x_{ij},\;
\sum_{g,j} u_{gj},\;
\sum_j y_j,\;
\sum_{(i,j)\in\mathcal{A}_{15}} x_{ij}
+\sum_{(i_1,i_2,j)\in\mathcal{F}_{15\text{–}29}} q_{i_1 i_2 j},\;
\sum_{(i,j)\in\mathcal{A}^{\mathrm{post}}_0} x_{ij},\;
\sum_{(i,j)\in\mathcal{A}:\,j\in R^{Z2}} x_{ij}
\Bigr) \\[10pt]
\text{s.t.}\quad
&\sum_{j\in R_i} x_{ij} \le 1
&& \forall\, i \\[4pt]
&x_{ij} \le y_j
&& \forall\, (i,j)\in\mathcal{A} \\[4pt]
&u_{gj} \ge x_{ij},\quad
u_{gj} \le \sum_{i\in E_g(j)} x_{ij}
&& \forall\, g,\,j\in R_g \\[4pt]
&\sum_{i\in E_{j,t}} x_{ij} \le \mathrm{cap}_j
&& \forall\, j,\,t \\[4pt]
&z_{cjt} \ge x_{ij}\ (i\in E_{j,t}\cap C_c),\quad
z_{cjt} \le \sum_{i\in E_{j,t}\cap C_c} x_{ij},\quad
\sum_c z_{cjt} \le 3
&& \forall\, j,\,t \\[4pt]
&\rho_{jt} \ge x_{ij}\ (i\in E_{j,t}\cap E^{\mathrm{RD}}), \\
&\sum_{i\in E_{j,t}} x_{ij}
  \le \mathrm{cap}_j - (\mathrm{cap}_j-20)\rho_{jt}
&& \forall\, j,\,t \text{ with } \mathrm{cap}_j>20 \\[4pt]
&\sum_{k\in E_{j,t_i}^{(-i)}} x_{kj}
  \le \mathrm{cap}_j(1-x_{ij})
&& \forall\, i\in E^{\mathrm{PRIV}},\, j\in R_i \\[4pt]
&x_{i_1 j}+x_{i_2 j} \le 1
&& \forall\, (i_1,i_2,j)\in\mathcal{F}_{15} \\[4pt]
&q_{i_1 i_2 j} \ge x_{i_1 j}+x_{i_2 j}-1
&& \forall\, (i_1,i_2,j)\in\mathcal{F}_{15\text{–}29} \\[4pt]
&x,y,u,z,\rho,q \in \{0,1\}.
\end{aligned}
\]

---

## 6. Post-solve booking windows (not part of the ILP)

Exam row times \(t^{\mathrm{start}}_i\), \(t^{\mathrm{end}}_i\) are **not** modified.
For each assigned pair with \(x_{ij}^\star=1\), a booking window is recorded:

\[
\begin{aligned}
\mathrm{pre}_{ij}
&=
\begin{cases}
30 & \text{if }(i,j)\in\mathcal{B}_{30}, \\
15 & \text{otherwise},
\end{cases}
\qquad
\mathrm{post}_{ij}
=
\begin{cases}
15 & \text{if }(i,j)\in\mathcal{B}^{\mathrm{post}}_{15}, \\
0 & \text{otherwise},
\end{cases} \\[8pt]
\mathrm{BookStart}_{ij}
&= t^{\mathrm{start}}_i - \mathrm{pre}_{ij},
\qquad
\mathrm{BookEnd}_{ij}
= t^{\mathrm{end}}_i + \mathrm{post}_{ij}.
\end{aligned}
\]

The returned `bookings` table is the set of distinct
\((\mathrm{Date},\,\mathrm{Room},\,\mathrm{BookStart},\,\mathrm{BookEnd})\)
tuples.

---

## 7. Variable / constraint map to code

| Math | Code (`gurobi_solver_grouped.py`) |
|---|---|
| \(x_{ij}\) | `x[(i, j)]` |
| \(y_j\) | `y[j]` |
| \(u_{gj}\) | `u[(g, j)]` |
| \(z_{cjt}\) | `z_g[(c, j, ts)]` |
| \(\rho_{jt}\) | `rd_flag_g[(j, ts)]` |
| \(q_{i_1 i_2 j}\) | `q[(i1, i2, j)]` |
| \(\mathcal{A}\) | `compat` |
| \(\mathcal{B}_{30}\) | `has_30_buffer` |
| \(\mathcal{B}^{\mathrm{post}}_{15}\) | `has_15_post_buffer` |
| \(\mathcal{F}_{15}\) | `inter_15_blocked` |
| \(\mathcal{F}_{15\text{–}29}\) | `inter_only_15` |
| \(E_{j,t}\) | `groups[j][ts]` |
| \(G\), \(E_g\) | `group_keys`, `exam_groups` |
