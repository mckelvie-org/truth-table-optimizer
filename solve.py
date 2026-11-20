#!/usr/bin/env python3
"""Exact synthesis of a 4-input function as a minimum 2-input NAND circuit (SAT).

Truth table: 4 hex digits, bit i = f(row i), with A = LSB of the row index
(row = D C B A). NOT is just NAND(x, x).

Finds the minimum gate count, then the minimum delay at that gate count, and
prints the netlist with each node's minimal sum-of-products.

Usage:
    python3 solve.py 4342            # min gates, then min delay
    python3 solve.py 0x4342 5        # min gates subject to delay <= 5
Requires: pip install python-sat
"""
import argparse, sys, itertools, time
from pysat.solvers import Cadical153

NIN = 4
"""Number of primary inputs. Nodes 0..NIN-1 are the inputs A..D."""

ROWS = 16
"""Number of truth table rows (2**NIN); row index bits are D C B A."""

NAMES = "ABCD"
"""Display names of the primary inputs, indexed by node number."""

FULL = (1 << ROWS) - 1
"""Truth table of the constant-1 function (all ROWS bits set)."""


def inval(j, t):
    """Return the value (0 or 1) of primary input j in truth table row t."""
    return (t >> j) & 1


# ---------------------------------------------------------------- SAT encoding
def solve(tt, r, max_depth=None):
    """Find a circuit of exactly r NAND gates computing truth table tt.

    Gates are nodes NIN..NIN+r-1, each a NAND of two earlier nodes (equal
    inputs make a NOT), and the last gate is the output. If max_depth is
    given, the output's gate delay must be at most max_depth.

    Return a list of gates [(node, (j, k))] in node order, or None if
    impossible.
    """
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
"""All 3**NIN product terms (cubes) over the inputs."""


def cube_mask(c):
    """Return the truth table of cube c: the set of rows where it is 1."""
    m = 0
    for t in range(ROWS):
        if all(v is None or inval(j, t) == v for j, v in enumerate(c)):
            m |= 1 << t
    return m


CUBE_MASK = {c: cube_mask(c) for c in CUBES}
"""Precomputed cube_mask() for every cube in CUBES."""


def cube_lits(c):
    """Return the number of literals in cube c (its non-don't-care entries)."""
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
    """Format truth table tt as a minimal sum of products, e.g. "A·B + C·¬D"."""
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
    """Verify that gates compute tt, then print the netlist and its stats.

    Each gate line is annotated with the minimal SOP of the function at
    that node, followed by the gate count, delay and critical path.

    Return (rows, summary): rows is [(gate, "NAND(x, y)", sop)] for each
    gate, and summary is "N gates, delay D".
    """
    out = gates[-1][0]
    name = lambda n: NAMES[n] if n < NIN else f"g{n - NIN + 1}"

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

    rows = [(name(i), f"NAND({name(j)}, {name(k)})", fmt_sop(func[i]))
            for i, (j, k) in gates]
    w = max(len(f"{g} = {defn}") for g, defn, _ in rows)
    for g, defn, sop in rows:
        lhs = f"{g} = {defn}"
        print(f"  {lhs:<{w}}   ; {sop}")
    print(f"  f = {name(out)}")
    print(f"\n  gates = {len(gates)}, delay = {depth[out]}")
    print(f"  critical path: {' -> '.join(path)}")
    return rows, f"{len(gates)} gates, delay {depth[out]}"


def parse_tt(s):
    """Parse a 4-hex-digit truth table, with optional 0x prefix, to an int.

    Used as an argparse type, so bad input raises ArgumentTypeError.
    """
    s = s.lower().removeprefix("0x")
    if len(s) != 4 or any(ch not in "0123456789abcdef" for ch in s):
        raise argparse.ArgumentTypeError(
            f"truth table must be 4 hex digits (e.g. 88F8), got {s!r}")
    return int(s, 16)


DESCRIPTION = """\
Find an optimal circuit for any 4-input boolean function f(A, B, C, D),
built only from 2-input NAND gates. NOT is a 1-input NAND, i.e. NAND(x, x),
and counts as one gate.

Constant 0 and 1 are not available as inputs, so a constant f is built
from gates: constant 1 (FFFF) takes 2 gates, NAND(x, NAND(x, x)), and
constant 0 (0000) takes 3. A copy of one input (e.g. AAAA) takes none.

The circuit is optimized first for the fewest NAND gates, and then, among
circuits with that gate count, for the lowest maximum gate delay (the number
of gates on the longest path from an input to f). Both are exact minimums
found with a SAT solver, not heuristics.
"""
"""Description shown at the top of --help."""

EPILOG = """\
truth table encoding:
  Number the 16 input combinations 0..15 with the 4-bit index DCBA, where
  A is the least significant bit and D the most significant:

      index = 8*D + 4*C + 2*B + A

  Bit <index> of a 16-bit integer is f's output for that combination.
  Write that integer as 4 hex digits. The rightmost hex digit covers
  indexes 0-3 (D=0, C=0), the next covers 4-7 (D=0, C=1), then 8-11
  (D=1, C=0), and the leftmost covers 12-15 (D=1, C=1).

  Example: f = A·B + C·¬D is true at indexes 3,4,5,6,7,11,15
           -> 0b1000_1000_1111_1000 = 0x88F8

output:
  One line per gate, gN = NAND(x, y), then f = gN naming the gate that
  drives the output. The comment on each gate line is that gate's
  function as a minimal sum of products (· = AND, + = OR, ¬ = NOT).
  Progress of the search is printed to stderr.

examples:
  %(prog)s 88F8        fewest gates, then lowest delay
  %(prog)s 0x6666      A XOR B (C and D unused)
  %(prog)s 88F8 3      fewest gates with delay <= 3, then lowest delay
  %(prog)s 88F8 -s     also open a schematic drawing in a web browser
  %(prog)s 88F8 -o circuit.svg
                       also save the schematic drawing as an SVG file

drawing:
  Gates are drawn left to right in columns by gate delay: inputs in
  column 0, and a gate with delay d in column d. A NOT (NAND(x, x)) is
  drawn with the NOT symbol.
"""
"""Text shown after the arguments in --help: encoding tutorial and examples."""


def main():
    """Command-line entry point: parse arguments, search, print the result.

    First finds the fewest gates (under the optional delay limit), then
    tightens the delay as far as possible at that gate count.
    """
    ap =argparse.ArgumentParser(
        description=DESCRIPTION, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("truth_table", type=parse_tt,
                    help="16-bit truth table as 4 hex digits, optional 0x prefix")
    ap.add_argument("max_delay", type=int, nargs="?",
                    help="only accept circuits with at most this many gate delays")
    ap.add_argument("-o", "--output", metavar="FILE",
                    help="write a schematic drawing to FILE: .svg for the "
                         "drawing alone, .html for a page with the drawing "
                         "and a table of gate functions")
    ap.add_argument("-s", "--show", action="store_true",
                    help="open the schematic drawing in a web browser")
    args = ap.parse_args()
    if args.output and not args.output.lower().endswith((".svg", ".html", ".htm")):
        ap.error("--output file name must end in .svg or .html")
    tt, max_depth = args.truth_table, args.max_delay
    print(f"f = 0x{tt:04X}   (A = LSB)   min SOP: {fmt_sop(tt)}\n")

    # trivial case: f is a primary input
    for j in range(NIN):
        if tt == sum(inval(j, t) << t for t in range(ROWS)):
            print(f"  f = {NAMES[j]}   (no gates needed)")
            output_drawing(args, tt, [], [], "0 gates, delay 0", out=j)
            return

    # 1) minimum gate count (optionally under a delay bound)
    for r in range(1, 30):
        t0 = time.time()
        gates = solve(tt, r, max_depth)
        print(f"  {r:2d} gates: {'SAT' if gates else 'UNSAT'} ({time.time() - t0:.1f}s)",
              file=sys.stderr, flush=True)
        if gates:
            break
    else:
        sys.exit(f"no circuit with delay <= {max_depth} computes 0x{tt:04X}")

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
    rows, summary = show(tt, gates)
    output_drawing(args, tt, gates, rows, summary)


def output_drawing(args, tt, gates, rows, summary, out=None):
    """Save and/or show the schematic, as requested by --output and --show.

    rows and summary are as returned by show(). out is the node driving f;
    it defaults to the last gate, and is the copied input when gates is empty.
    """
    if not (args.output or args.show):
        return
    import draw  # only drawing needs schemdraw

    svg = draw.draw_svg(gates, NIN, NAMES, out=out)
    title = f"f = 0x{tt:04X}: {fmt_sop(tt)} ({summary})"
    page = draw.html_page(title, svg, rows)
    if args.output:
        is_svg = args.output.lower().endswith(".svg")
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(svg if is_svg else page)
        print(f"\n  drawing written to {args.output}")
    if args.show:
        draw.open_in_browser(page)


if __name__ == "__main__":
    main()
