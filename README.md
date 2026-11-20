# truth-table-optimizer

Finds an optimal circuit for any 4-input boolean function, built only from
2-input NAND gates.

You give it a truth table as a 16-bit hex number, and it prints a netlist that
computes the function with:

1. **the fewest NAND gates possible**, and then, among circuits with that
   minimum gate count,
2. **the lowest possible maximum gate delay**: the number of gates on the
   longest path from an input to the output.

Gate count always comes first. The tool never adds a gate to save delay
unless you give it a delay limit (see [Limiting delay](#limiting-delay)).
Both results are exact minimums found with a SAT solver, not heuristics.

The result uses only NAND gates. NOT appears as a 1-input NAND, written
`NAND(x, x)`, and counts as one gate and one gate delay like any other NAND.

## Where this is useful

This tool helps with any puzzle or design where you build logic from NAND
gates and gate count or speed matters. One example is the Steam game
[IT THINKS! Build Your Own GPU](https://store.steampowered.com/app/5196330/IT_THINKS_Build_Your_Own_GPU/),
where you wire up logic gate by gate. When a level needs a particular 4-input
function, write down its truth table, run this tool, and copy the netlist.

## Installation

Requires Python 3.14 or newer, [python-sat](https://pypi.org/project/python-sat/),
and [schemdraw](https://schemdraw.readthedocs.io/) (used only for drawings).

```bash
pdm install                 # or: pip install python-sat schemdraw
python3 solve.py --help
```

## Writing a truth table as a hex number

The function has four inputs, `A`, `B`, `C` and `D`. There are 16
combinations of input values. Number each combination with a 4-bit
**index** formed by the input values, with **`A` as the least significant
bit (LSB)** and **`D` as the most significant bit (MSB)**:

```
index = 8·D + 4·C + 2·B + A        (bits written D C B A)
```

The truth table is a 16-bit integer. Bit number `index` is the function's
output for that input combination. Write that integer as 4 hex digits.

Each hex digit covers four rows that share the same `D` and `C`:

| hex digit      | indexes | D | C | the digit's bits 3,2,1,0 are rows with B,A = |
|----------------|---------|---|---|----------------------------------------------|
| 4th (leftmost) | 12–15   | 1 | 1 | 11, 10, 01, 00                               |
| 3rd            | 8–11    | 1 | 0 | 11, 10, 01, 00                               |
| 2nd            | 4–7     | 0 | 1 | 11, 10, 01, 00                               |
| 1st (rightmost)| 0–3     | 0 | 0 | 11, 10, 01, 00                               |

### Example: f = A·B + C·¬D

"f is true when A and B are both 1, or when C is 1 and D is 0."

Fill in the table, one row per index:

| index | D | C | B | A | A·B | C·¬D | f |
|------:|---|---|---|---|-----|------|---|
|  0    | 0 | 0 | 0 | 0 | 0   | 0    | 0 |
|  1    | 0 | 0 | 0 | 1 | 0   | 0    | 0 |
|  2    | 0 | 0 | 1 | 0 | 0   | 0    | 0 |
|  3    | 0 | 0 | 1 | 1 | 1   | 0    | 1 |
|  4    | 0 | 1 | 0 | 0 | 0   | 1    | 1 |
|  5    | 0 | 1 | 0 | 1 | 0   | 1    | 1 |
|  6    | 0 | 1 | 1 | 0 | 0   | 1    | 1 |
|  7    | 0 | 1 | 1 | 1 | 1   | 1    | 1 |
|  8    | 1 | 0 | 0 | 0 | 0   | 0    | 0 |
|  9    | 1 | 0 | 0 | 1 | 0   | 0    | 0 |
| 10    | 1 | 0 | 1 | 0 | 0   | 0    | 0 |
| 11    | 1 | 0 | 1 | 1 | 1   | 0    | 1 |
| 12    | 1 | 1 | 0 | 0 | 0   | 0    | 0 |
| 13    | 1 | 1 | 0 | 1 | 0   | 0    | 0 |
| 14    | 1 | 1 | 1 | 0 | 0   | 0    | 0 |
| 15    | 1 | 1 | 1 | 1 | 1   | 0    | 1 |

Read the `f` column from index 15 at the left down to index 0 at the right,
in groups of four:

```
index:  15 14 13 12 | 11 10  9  8 |  7  6  5  4 |  3  2  1  0
f:       1  0  0  0 |  1  0  0  0 |  1  1  1  1 |  1  0  0  0
hex:          8     |       8     |       F     |       8
```

The truth table is **`88F8`**.

Two quick checks:

* `A` alone is `AAAA`, `B` is `CCCC`, `C` is `F0F0` and `D` is `FF00`.
* A function that ignores `C` and `D` repeats one hex digit four times.
  For example, A XOR B is `6666`.

## Running it

```console
$ python3 solve.py 88F8
f = 0x88F8   (A = LSB)   min SOP: A·B + C·¬D


  g1 = NAND(A, B)     ; ¬A + ¬B
  g2 = NAND(C, D)     ; ¬C + ¬D
  g3 = NAND(C, g2)    ; D + ¬C
  g4 = NAND(g1, g3)   ; A·B + C·¬D
  f = g4

  gates = 4, delay = 3
  critical path: g2 -> g3 -> g4
```

How to read the output:

* The first line repeats the truth table and gives its minimal
  sum of products (SOP), where `·` is AND, `+` is OR and `¬` is NOT.
* Each gate line, `gN = NAND(x, y)`, is one NAND gate. Its inputs are
  primary inputs `A`–`D` or earlier gates. A NOT gate appears as
  `NAND(x, x)`.
* `f = g4` names the gate that drives the output. Like `A`–`D` for the
  inputs, `f` is a signal name, not a gate.
* The comment after `;` is the function computed at that gate, so you can
  check the circuit step by step.
* `gates` is the total NAND count, NOTs included. `delay` is the number of
  gates on the longest input-to-output path, and `critical path` lists the
  gates along that path.
* When several circuits tie on gates and delay, the tool prints one of
  them. In this example `g3 = NAND(C, NAND(C, D))` computes `¬(C·¬D)`.
  `NAND(C, NAND(D, D))` would do the same with equal gates and delay.

Search progress, such as `3 gates: UNSAT`, is printed to stderr. Add
`2>/dev/null` to hide it.

The hex value is case-insensitive and may start with `0x`.

### Drawing the circuit

Two options draw the circuit as a schematic:

* `-o FILE` / `--output FILE` saves the drawing. A `.svg` name saves just
  the drawing. A `.html` name saves a page with the drawing and a table of
  each gate's definition and function.
* `-s` / `--show` opens that page in your web browser. Under WSL it opens
  in the Windows default browser.

```bash
python3 solve.py 88F8 -o 88F8.svg
python3 solve.py 88F8 --show
```

![Schematic for 88F8](docs/88F8.svg)

The drawing is laid out left to right by gate delay. The inputs are in
column 0, and a gate with delay *d* is in column *d*, so the number of
columns after the inputs is the circuit's delay. Each gate gets its own row,
so wires never pass through other gates. A NOT gate, `NAND(x, x)`, is drawn
with the NOT symbol. A dot marks where a wire branches; wires that cross
without a dot are not connected.

### Limiting delay

A second argument sets a maximum delay:

```bash
python3 solve.py 88F8 3
```

The tool then finds the fewest gates among circuits with at most that delay,
and lowers the delay further if it can at that gate count. If no circuit can
meet the limit, it says so. For example, `88F8 2` is impossible.

## License

MIT
