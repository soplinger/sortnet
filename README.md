# sortnet

**Verify, analyse, prune and generate comparator sorting networks, offline, from plain text.**

`sortnet` takes a sorting network written as a short text file and tells you whether it really sorts, how big and deep it is, which comparators are dead weight, and how it compares with the best-known networks. It can also draw the network, run it on your numbers step by step, prune it, and generate Batcher's and odd-even transposition networks for any width.

Everything is one Python 3 file using only the standard library. There are no servers, accounts, API keys or network calls.

## Why

A comparator network is a fixed sequence of compare-and-swap steps, used for sorting in hardware, GPUs and constant-time code. Checking that a network sorts by testing random lists is unreliable. `sortnet` uses the **0-1 principle**: a network sorts every input exactly when it sorts every input made of 0s and 1s. For widths up to 20 that is only 2^20 inputs, so the check is an exhaustive proof, not a guess.

## Features

1. **Exact verification.** `check` proves a network sorts by running all 2^n 0-1 inputs at once, using bit-parallel integers. Any failure comes with a concrete 0-1 counterexample.
2. **Sampling above the proof limit.** Above `--max-exhaustive` (default 20 wires) it tests seeded random 0-1 inputs and says clearly that the result is evidence, not proof.
3. **Statistics.** `stats` reports comparator count, depth, a ⌈log₂ n⌉ depth lower bound, whether it sorts, and how many comparators never exchange values.
4. **Best-known comparison.** `stats` and `bounds` compare against published best-known sizes and depths for widths 1 to 16.
5. **Line-numbered lint.** `lint` reports malformed lines, self-comparators and out-of-range wires with `file:line`. Warnings cover high-to-low comparators, dead comparators and unused wires. `--strict` promotes warnings to failures.
6. **ASCII diagrams.** `diagram` draws wires left to right with each comparator in its parallel layer.
7. **Parallel layers.** `layers` lists which comparators run together in each layer.
8. **Run on your data.** `apply` sorts a list of integers or decimals through the network. `--trace` prints the list after every layer.
9. **Pruning.** `prune` removes comparators that never swap, then greedily removes any whose removal still leaves a sorting network, and writes the result back as a file with a removal report.
10. **Generators.** `generate` writes Batcher's odd-even merge sort or odd-even transposition sort for any width, grouped by layer.
11. **Exact equivalence.** `compare` checks whether two networks produce identical outputs on every 0-1 input (which makes them identical functions) and prints a differing input if not.
12. **CI-friendly.** Exit codes are `0` for success, `1` for a failed check or lint, and `2` for unreadable or invalid input. `check` and `stats` accept `--json`.

## Quick start

Save this as `net4.txt`:

```text
# Optimal 4-wire sorting network: 5 comparators, depth 3.
wires 4
0 1
2 3
0 2
1 3
1 2
```

Then run:

```sh
python3 sortnet.py check net4.txt        # proves it sorts
python3 sortnet.py stats net4.txt       # size, depth, best-known comparison
python3 sortnet.py diagram net4.txt     # ASCII picture
python3 sortnet.py apply net4.txt 4 3 2 1 --trace
```

## Network file format

- An optional `wires N` line sets the width. If it is missing, the width is the highest wire used plus one.
- Each comparator is one line, `i j`, or `i,j`. The smaller value goes to wire `i` and the larger to wire `j`.
- `#` starts a comment. Blank lines are ignored.

## Usage

```text
python3 sortnet.py check FILE [--json] [--max-exhaustive N] [--samples N] [--seed S]
python3 sortnet.py stats FILE [--json] [--max-exhaustive N] [--samples N] [--seed S]
python3 sortnet.py lint FILE [--strict] [--max-exhaustive N]
python3 sortnet.py diagram FILE
python3 sortnet.py layers FILE
python3 sortnet.py apply FILE VALUE... [--trace]
python3 sortnet.py prune FILE [-o OUT] [--max-exhaustive N]
python3 sortnet.py generate {oddeven,transposition} N [-o OUT]
python3 sortnet.py compare FILE_A FILE_B [--max-exhaustive N]
python3 sortnet.py bounds [N]
```

Exhaustive checks accept widths up to 24. The default is 20. Larger widths use sampling.

## Examples

`examples/net4.txt` is the optimal 4-wire network. `examples/fail3.txt` is a 3-wire network that does not sort. `examples/messy.txt` exercises the lint command.

## Running the tests

The tests need `pytest`. From the project root:

```sh
python3 -m pytest -q
```

The tests cover parsing with line numbers, bit-parallel inputs, exhaustive and sampled checks, counterexamples, Batcher and transposition generators, layering, dead-comparator detection, pruning, equivalence, value tracing, diagrams, lint, the bounds table and CLI exit codes.

## Limits

- Exhaustive checks cost 2^n time and memory. Widths above 24 are not accepted for exhaustive work, and widths above 20 use sampling by default.
- The best-known table covers widths 1 to 16 only. Values come from the published literature and are reported as reference points, not recomputed.
- Pruning and comparison rely on exhaustive checks, so they need widths within `--max-exhaustive`.
