#!/usr/bin/env python3
"""Exact synthesis of a 4-input function as a minimum 2-input NAND circuit (SAT).

Truth table: 4 hex digits, bit i = f(row i), with A = LSB of the row index
(row = D C B A). NOT is just NAND(x, x).

Finds the minimum gate count, then the minimum delay at that gate count, and
prints the netlist with each node's minimal sum-of-products.

Usage:
    python3 nand_synth.py 4342            # min gates, then min delay
    python3 nand_synth.py 0x4342 5        # min gates subject to delay <= 5
Requires: pip install python-sat
"""
import sys, itertools, time
from pysat.solvers import Cadical153

NIN, ROWS = 4, 16
NAMES = "ABCD"
FULL = (1 << ROWS) - 1


def inval(j, t):
    return (t >> j) & 1


# ---------------------------------------------------------------- SAT encoding
def solve(tt, r, max_depth=None):
    """Return a list of gates [(node, (j, k))] or None if impossible."""
    nv = [0]

    def new():
        nv[0] += 1
        return nv[0]

    cls = []
    N = NIN + r
    val = {(i, t): new() for i in range(NIN, N) for t in range(ROWS)}
    sel = {}
    for i in range(NIN, N):
        pairs = [(j, k) for j in range(i) for k in range(j, i)]
        for p in pairs:
            sel[i, p] = new()
        lits = [sel[i, p] for p in pairs]
        cls.append(lits)
        cls += [[-a, -b] for a, b in itertools.combinations(lits, 2)]

    def lit(node, t):
        return (True, inval(node, t)) if node < NIN else (False, val[node, t])

    for (i, (j, k)), s in sel.items():
        for t in range(ROWS):
            g = val[i, t]
            ins = [lit(j, t), lit(k, t)]
            # (vj and vk) -> not g
            c, sat = [-s, -g], False
            for const, v in ins:
                if const:
                    sat |= v == 0
                else:
                    c.append(-v)
            if not sat:
                cls.append(c)
            # not v -> g, for each input
            for const, v in ins:
                if const:
                    if v == 0:
                        cls.append([-s, g])
                else:
                    cls.append([-s, v, g])

    out = N - 1
    for t in range(ROWS):
        cls.append([val[out, t]] if (tt >> t) & 1 else [-val[out, t]])

    # symmetry breaking: every non-output gate feeds a later gate
    for i in range(NIN, N - 1):
        cls.append([s for (g, (j, k)), s in sel.items() if g > i and i in (j, k)])

    if max_depth is not None:
        le = {(i, L): new() for i in range(NIN, N) for L in range(max_depth + 1)}
        cls.append([le[out, max_depth]])
        for i in range(NIN, N):
            cls.append([-le[i, 0]])
        for (i, (j, k)), s in sel.items():
            for L in range(1, max_depth + 1):
                for x in (j, k):
                    if x >= NIN:
                        cls.append([-s, -le[i, L], le[x, L - 1]])

    with Cadical153(bootstrap_with=cls) as S:
        if not S.solve():
            return None
        m = {l for l in S.get_model() if l > 0}
        return sorted((i, p) for (i, p), s in sel.items() if s in m)


# ------------------------------------------------- minimal SOP (exact, 4 vars)
# A cube is a tuple of 4 entries, each 0, 1 or None (don't care).
CUBES = list(itertools.product((0, 1, None), repeat=NIN))


def cube_mask(c):
    m = 0
    for t in range(ROWS):
        if all(v is None or inval(j, t) == v for j, v in enumerate(c)):
            m |= 1 << t
    return m


CUBE_MASK = {c: cube_mask(c) for c in CUBES}


def cube_lits(c):
    return sum(v is not None for v in c)


def min_sop(tt):
    """Exact minimum SOP: fewest terms, then fewest literals."""
    if tt == 0:
        return []
    implicants = [c for c in CUBES if CUBE_MASK[c] & ~tt == 0]
    primes = [c for c in implicants
              if not any(d != c and CUBE_MASK[c] & ~CUBE_MASK[d] == 0
                         for d in implicants)]
    for n in range(1, len(primes) + 1):
        best = None
        for combo in itertools.combinations(primes, n):
            m = 0
            for c in combo:
                m |= CUBE_MASK[c]
            if m == tt:
                cost = sum(cube_lits(c) for c in combo)
                if best is None or cost < best[0]:
                    best = (cost, combo)
        if best:
            return list(best[1])
    raise AssertionError


def fmt_sop(tt):
    if tt == 0:
        return "0"
    if tt == FULL:
        return "1"
    terms = []
    for c in min_sop(tt):
        lits = [("" if v else "¬") + NAMES[j] for j, v in enumerate(c) if v is not None]
        terms.append("·".join(lits))
    terms.sort(key=lambda s: (s.count("·"), s))
    return " + ".join(terms)


# ------------------------------------------------------------------ printing
def show(tt, gates):
    out = gates[-1][0]
    name = lambda n: NAMES[n] if n < NIN else ("f" if n == out else f"g{n - NIN + 1}")

    func = {n: sum(inval(n, t) << t for t in range(ROWS)) for n in range(NIN)}
    depth = {n: 0 for n in range(NIN)}
    for i, (j, k) in gates:
        func[i] = FULL ^ (func[j] & func[k])
        depth[i] = 1 + max(depth[j], depth[k])
    assert func[out] == tt, "verification failed"

    # critical path
    path, n = [], out
    while n >= NIN:
        path.append(name(n))
        j, k = dict(gates)[n]
        n = j if depth[j] >= depth[k] else k
    path.reverse()

    w = max(len(f"{name(i)} = NAND({name(j)}, {name(k)})") for i, (j, k) in gates)
    for i, (j, k) in gates:
        lhs = f"{name(i)} = NAND({name(j)}, {name(k)})"
        print(f"  {lhs:<{w}}   ; {fmt_sop(func[i])}")
    print(f"\n  gates = {len(gates)}, delay = {depth[out]}")
    print(f"  critical path: {' -> '.join(path)}")


def parse_tt(s):
    s = s.lower().removeprefix("0x")
    if len(s) != 4 or any(ch not in "0123456789abcdef" for ch in s):
        sys.exit(f"truth table must be 4 hex digits (e.g. 4342), got {s!r}")
    return int(s, 16)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tt = parse_tt(sys.argv[1])
    max_depth = int(sys.argv[2]) if len(sys.argv) > 2 else None
    print(f"f = 0x{tt:04X}   (A = LSB)   min SOP: {fmt_sop(tt)}\n")

    # trivial case: f is a primary input
    for j in range(NIN):
        if tt == sum(inval(j, t) << t for t in range(ROWS)):
            print(f"  f = {NAMES[j]}   (no gates needed)")
            return

    # 1) minimum gate count (optionally under a delay bound)
    for r in range(1, 30):
        t0 = time.time()
        gates = solve(tt, r, max_depth)
        print(f"  {r:2d} gates: {'SAT' if gates else 'UNSAT'} ({time.time() - t0:.1f}s)",
              file=sys.stderr, flush=True)
        if gates:
            break

    # 2) at that gate count, tighten delay as far as it goes
    def delay(g):
        d = {n: 0 for n in range(NIN)}
        for i, (j, k) in g:
            d[i] = 1 + max(d[j], d[k])
        return d[g[-1][0]]

    while True:
        better = solve(tt, r, delay(gates) - 1)
        if not better:
            break
        gates = better
        print(f"  {r:2d} gates, delay {delay(gates)}: SAT", file=sys.stderr, flush=True)

    print()
    show(tt, gates)


if __name__ == "__main__":
    main()
