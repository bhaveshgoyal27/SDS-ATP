# 📘 Exam Room Allocation Optimization Model

## 1. Sets and Indices

- \( i \in E \): set of exams (each exam = one student)
- \( j \in R \): set of room-time slots
- \( c \in C \): set of courses

---

## 2. Parameters

### Room parameters
- \( \text{cap}_j \): capacity of room \( j \)
- \( \text{zone}_j \in \{1,2\} \): zone of room \( j \)
- \( \text{date}_j \), \( \text{start}_j \), \( \text{end}_j \): schedule of room \( j \)

### Exam parameters
- \( \text{date}_i \), \( \text{start}_i \), \( \text{end}_i \): schedule of exam \( i \)
- \( \text{course}(i) \in C \): course of exam \( i \)
- \( \text{RD}_i \in \{0,1\} \): reduced distraction flag
- \( \text{PRIV}_i \in \{0,1\} \): private room requirement

### Compatibility
- \( A \subseteq E \times R \): set of feasible assignments  

\[
(i,j) \in A \iff
\begin{cases}
\text{date}_i = \text{date}_j \\
\text{start}_i \ge \text{start}_j + 15 \\
\text{end}_i \le \text{end}_j
\end{cases}
\]

---

## 3. Decision Variables

### Assignment
\[
x_{ij} =
\begin{cases}
1 & \text{if exam } i \text{ assigned to room } j \\
0 & \text{otherwise}
\end{cases}
\]

### Room usage
\[
y_j =
\begin{cases}
1 & \text{if room } j \text{ is used} \\
0 & \text{otherwise}
\end{cases}
\]

### Course-room usage
\[
z_{cj} =
\begin{cases}
1 & \text{if course } c \text{ uses room } j \\
0 & \text{otherwise}
\end{cases}
\]

### Reduced distraction flag
\[
r_j =
\begin{cases}
1 & \text{if any RD student assigned to room } j \\
0 & \text{otherwise}
\end{cases}
\]

---

## 4. Constraints

### (C1) Each exam assigned to at most one room
\[
\sum_{j \in R : (i,j)\in A} x_{ij} \le 1 \quad \forall i \in E
\]

---

### (C2) Assignment implies room usage
\[
x_{ij} \le y_j \quad \forall (i,j) \in A
\]

---

### (C3) Room capacity
\[
\sum_{i \in E : (i,j)\in A} x_{ij} \le \text{cap}_j \quad \forall j \in R
\]

---

### (C4) Course-room linkage
\[
z_{cj} \ge x_{ij} \quad \forall i \text{ with } \text{course}(i)=c
\]

\[
z_{cj} \le \sum_{i:\text{course}(i)=c} x_{ij}
\]

---

### (C5) Max 3 courses per room
\[
\sum_{c \in C} z_{cj} \le 3 \quad \forall j \in R
\]

---

### (C6) Reduced distraction constraint

Activate RD flag:
\[
r_j \ge x_{ij} \quad \forall i \text{ with } \text{RD}_i=1
\]

Capacity restriction:
\[
\sum_{i} x_{ij} \le 20 \cdot r_j + \text{cap}_j \cdot (1 - r_j)
\]

---

### (C7) Private room constraint
\[
\sum_{k \ne i} x_{kj} \le \text{cap}_j \cdot (1 - x_{ij})
\]

---

### (C8) Overlapping room slots

For overlapping slots \( j_1, j_2 \):
\[
\sum_{i} x_{i j_1} + \sum_{i} x_{i j_2} \le \text{cap}
\]

---

## 5. Objective Function (Hierarchical)

### Priority 1: Maximize assignments
\[
\max \sum_{(i,j)\in A} x_{ij}
\]

---

### Priority 2: Minimize rooms used
\[
\min \sum_{j} y_j
\]

---

### Priority 3: Prefer 30-min buffer
\[
\min \sum_{(i,j)\in A: B^{30}_{ij}=0} x_{ij}
\]

---

### Priority 4: Prefer 15-min post buffer
\[
\min \sum_{(i,j)\in A: B^{15}_{ij}=0} x_{ij}
\]

---

### Priority 5: Prefer Zone 1 rooms
\[
\min \sum_{(i,j)\in A: \text{zone}_j \ne 1} x_{ij}
\]

---

## 6. Final Formulation

**Lexicographic optimization:**

1. Maximize assigned exams  
2. Minimize rooms used  
3. Minimize lack of 30-min buffer  
4. Minimize lack of 15-min post buffer  
5. Minimize use of non-Zone-1 rooms  

---

## 7. Variable Domains

\[
x_{ij}, y_j, z_{cj}, r_j \in \{0,1\}
\]

---

## 8. Interpretation

- Each student is assigned to at most one room  
- Rooms respect capacity and special constraints  
- Optimization prioritizes:
  1. Feasibility (assign as many students as possible)
  2. Efficiency (use fewer rooms)
  3. Quality (better buffers and zones)
  