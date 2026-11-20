"""Draw a NAND netlist as a left-to-right schematic using schemdraw.

Gates are placed in columns by gate delay depth: the primary inputs are in
column 0 and a gate with delay d is in column d. Every node gets its own row,
so a horizontal wire into a gate never runs through another gate. Each node's
output drops onto its own vertical lane in the channel to the right of its
column, and horizontal taps run from the lane to the gates it feeds.
"""
import html
import itertools
import os
import platform
import shutil
import subprocess
import tempfile
import webbrowser

import schemdraw
import schemdraw.elements as elm
import schemdraw.logic as logic

GATE_W = 1.85
"""Width of a NAND symbol including its leads; every gate column is this wide."""

PIN_DY = 0.25
"""Vertical offset of a NAND's two input pins from its center line."""

ROW_H = 1.7
"""Vertical spacing between rows; each node occupies its own row."""

LANE_W = 0.35
"""Horizontal spacing between vertical wire lanes in a channel."""

INPUT_W = 0.6
"""Length of the lead drawn from each primary input label."""

MAX_PERMUTE = 7
"""Largest channel whose lane order is chosen by trying every permutation."""


def _depths(gates, nin):
    """Return {node: gate delay depth}, with primary inputs at depth 0."""
    depth = {n: 0 for n in range(nin)}
    for i, (j, k) in gates:
        depth[i] = 1 + max(depth[j], depth[k])
    return depth


def _row_order(gates, nin, used_inputs):
    """Return nodes in top-to-bottom row order.

    Each gate sits near the average row position of its sources (a barycenter
    ordering), which keeps wires short and limits crossings.
    """
    pos = {n: float(n) for n in used_inputs}
    for i, (j, k) in gates:
        pos[i] = (pos[j] + pos[k]) / 2
    depth = _depths(gates, nin)
    return sorted(pos, key=lambda n: (pos[n], depth[n], n))


def _lane_crossings(order, spans, row_y, sinks):
    """Count wire crossings inside one channel for a given lane order.

    order lists source nodes from left to right. A source's stub enters its
    lane from the left at its own row, crossing lanes to its left that span
    that row. Its taps leave to the right, crossing lanes to the right that
    span the tap's row.
    """
    n = 0
    for a, s in enumerate(order):
        for b, t in enumerate(order):
            lo, hi = spans[t]
            if b < a and lo < row_y[s] < hi:
                n += 1
            if b > a:
                n += sum(lo < y < hi for y in sinks[s])
    return n


def draw_svg(gates, nin, names, out_name="f", gate_name=None):
    """Return an SVG drawing of the netlist as a string.

    gates is [(node, (j, k))] in node order, as returned by solve(); a gate
    with j == k is drawn as a NOT. names gives the primary input labels.
    gate_name(node) gives each gate's label. The last gate drives the output
    signal, whose wire is labeled out_name.
    """
    out = gates[-1][0]
    gate_name = gate_name or (lambda n: f"g{n - nin + 1}")
    depth = _depths(gates, nin)
    ins = dict(gates)
    sinks_of = {}
    for i, (j, k) in gates:
        for s in {j, k}:
            sinks_of.setdefault(s, []).append(i)
    used_inputs = [n for n in range(nin) if n in sinks_of]

    rows = _row_order(gates, nin, used_inputs)
    row_y = {n: -r * ROW_H for r, n in enumerate(rows)}

    def pin_ys(i):
        """Return [(source, y)] for the input pins of gate i."""
        j, k = ins[i]
        if j == k:
            return [(j, row_y[i])]
        return [(j, row_y[i] + PIN_DY), (k, row_y[i] - PIN_DY)]

    taps = {s: [] for s in sinks_of}
    for i, _ in gates:
        for s, y in pin_ys(i):
            taps[s].append(y)

    # Channel c lies to the right of column c and holds one lane per node in
    # column c that feeds later gates. Order lanes to minimize crossings.
    ncols = depth[out] + 1
    lanes = {}
    for c in range(ncols - 1):
        srcs = [n for n in rows if depth[n] == c and n in sinks_of]
        spans = {s: (min(taps[s] + [row_y[s]]), max(taps[s] + [row_y[s]]))
                 for s in srcs}
        if len(srcs) <= MAX_PERMUTE:
            best = min(itertools.permutations(srcs),
                       key=lambda o: _lane_crossings(o, spans, row_y, taps))
        else:
            best = srcs
        lanes[c] = list(best)

    # x coordinates: column c spans [col_x[c], col_x[c] + width], then its
    # channel follows.
    col_x, x = [], 0.0
    for c in range(ncols):
        col_x.append(x)
        x += INPUT_W if c == 0 else GATE_W
        if c < ncols - 1:
            x += (len(lanes[c]) + 1) * LANE_W
    out_x = lambda n: col_x[depth[n]] + (INPUT_W if depth[n] == 0 else GATE_W)
    lane_x = {s: out_x(s) + (a + 1) * LANE_W
              for c in lanes for a, s in enumerate(lanes[c])}

    with schemdraw.Drawing(show=False) as d:
        d.config(fontsize=12, bgcolor="white")
        for n in used_inputs:
            y = row_y[n]
            d.add(elm.Line().at((0, y)).to((INPUT_W, y))
                  .label(names[n], loc="left"))

        for i, (j, k) in gates:
            x0, y = col_x[depth[i]], row_y[i]
            if j == k:
                # Not is a 2-terminal element; its leads stretch to fill length
                d.add(logic.Not().length(GATE_W).anchor("start").at((x0, y)))
            else:
                d.add(logic.Nand().anchor("in1").at((x0, y + PIN_DY)))
            d.add(elm.Label().at((x0 + GATE_W / 2, y + 0.7)).label(gate_name(i)))
            if i == out:
                d.add(elm.Line().at((x0 + GATE_W, y)).to((x0 + GATE_W + 0.6, y))
                      .label(out_name, loc="right"))

        for s, ys in taps.items():
            lx, sy = lane_x[s], row_y[s]
            d.add(elm.Line().at((out_x(s), sy)).to((lx, sy)))
            lo, hi = min(ys + [sy]), max(ys + [sy])
            if hi > lo:
                d.add(elm.Line().at((lx, lo)).to((lx, hi)))
            for y in set(ys + [sy]):
                if lo < y < hi:
                    d.add(elm.Dot(radius=0.06).at((lx, y)))

        for i, _ in gates:
            for s, y in pin_ys(i):
                d.add(elm.Line().at((lane_x[s], y)).to((col_x[depth[i]], y)))

        return d.get_imagedata("svg").decode()


def html_page(title, svg, rows):
    """Return a standalone HTML page showing svg above a table of rows.

    rows is a list of (gate, definition, function) string triples.
    """
    body = "\n".join(
        f"<tr><td>{html.escape(g)}</td><td><code>{html.escape(defn)}</code></td>"
        f"<td>{html.escape(fn)}</td></tr>" for g, defn, fn in rows)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2em; background: #fff; color: #111; }}
  .circuit svg {{ max-width: 100%; height: auto; }}
  table {{ border-collapse: collapse; margin-top: 1.5em; }}
  td, th {{ padding: 0.25em 1em; border-bottom: 1px solid #ddd; text-align: left; }}
</style></head>
<body><h1>{html.escape(title)}</h1>
<div class="circuit">{svg}</div>
<table><tr><th>gate</th><th>definition</th><th>function</th></tr>
{body}
</table></body></html>
"""


def open_in_browser(page):
    """Write an HTML page to a temporary file and open it in a web browser.

    Under WSL, where Linux has no browser, the page is opened in the Windows
    default browser instead. Returns the temporary file's path.
    """
    fd, path = tempfile.mkstemp(suffix=".html", prefix="nand-circuit-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(page)
    wsl = "microsoft" in platform.release().lower()
    if wsl and shutil.which("wslpath") and shutil.which("explorer.exe"):
        win = subprocess.run(["wslpath", "-w", path], capture_output=True,
                             text=True, check=True).stdout.strip()
        # explorer.exe exits nonzero even on success, so don't check it
        subprocess.run(["explorer.exe", win])
    elif not webbrowser.open("file://" + path):
        print(f"could not open a browser; the drawing is in {path}")
    return path
