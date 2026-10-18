#!/usr/bin/env python3
"""sortnet: verify, analyse, prune and generate comparator sorting networks.

A network is a plain-text file. An optional ``wires N`` line sets the width,
then each comparator is one line ``i j``. A comparator puts the smaller value
on wire ``i`` and the larger on wire ``j``. ``#`` starts a comment.

Verification uses the 0-1 principle, done bit-parallel: each wire is a Python
int whose bit ``x`` holds that wire's value for 0-1 input ``x``. A network
sorts every input exactly when it sorts every 0-1 input, so the exhaustive
check is a proof. Wider networks fall back to seeded random 0-1 sampling,
which is reported as evidence rather than proof.
"""

import argparse
import json
import random
import re
import sys
from dataclasses import dataclass, field

COMPARATOR_RE = re.compile(r"^(\d+)[\s,]+(\d+)$")

# Best known (comparators, depth) per width, from the sorting-network
# literature (Knuth TAOCP vol. 3 and later optimal-size and optimal-depth work).
BEST_KNOWN = {
    1: (0, 0), 2: (1, 1), 3: (3, 3), 4: (5, 3), 5: (9, 5), 6: (12, 5),
    7: (16, 6), 8: (19, 6), 9: (25, 7), 10: (29, 7), 11: (35, 8),
    12: (39, 8), 13: (45, 9), 14: (51, 9), 15: (56, 9), 16: (60, 9),
}

DEFAULT_MAX_EXHAUSTIVE = 20
DEFAULT_SAMPLES = 4096
DEFAULT_SEED = 0


class SortnetError(Exception):
    """A problem with the input that is reported to the user."""


@dataclass
class Network:
    wires: int
    comps: list
    lines: list = field(default_factory=list)

    def layers(self):
        """Return (layer number per comparator, depth) using ASAP layering."""
        last = [0] * self.wires
        numbers = []
        for i, j in self.comps:
            k = max(last[i], last[j]) + 1
            last[i] = last[j] = k
            numbers.append(k)
        return numbers, max(numbers, default=0)


def parse_text(text):
    """Parse network text. Returns (Network, errors) with errors as (line, message)."""
    wires = None
    comps, lines, errors = [], [], []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        body = raw.split("#", 1)[0].strip()
        if not body:
            continue
        head = body.split()
        if head[0].lower() == "wires":
            if len(head) != 2 or not head[1].isdigit() or int(head[1]) < 1:
                errors.append((lineno, "'wires' must be followed by one positive integer"))
            elif wires is not None:
                errors.append((lineno, "duplicate 'wires' line"))
            else:
                wires = int(head[1])
            continue
        match = COMPARATOR_RE.match(body)
        if not match:
            errors.append((lineno, f"expected 'i j' or 'wires N', found {body!r}"))
            continue
        i, j = int(match.group(1)), int(match.group(2))
        if i == j:
            errors.append((lineno, f"comparator {i} {j} compares a wire with itself"))
            continue
        comps.append((i, j))
        lines.append(lineno)
    if wires is None:
        wires = max((max(c) for c in comps), default=-1) + 1
    for (i, j), lineno in zip(comps, lines):
        if max(i, j) >= wires:
            errors.append((lineno, f"wire {max(i, j)} is outside 0..{wires - 1}"))
    return Network(wires, comps, lines), sorted(errors)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise SortnetError(f"{path}: cannot read file: {exc.strerror}")


def load_network(path):
    net, errors = parse_text(read_text(path))
    if errors:
        raise SortnetError("\n".join(f"{path}:{ln}: error: {msg}" for ln, msg in errors))
    if net.wires < 1:
        raise SortnetError(f"{path}: empty network; add comparators or a 'wires N' line")
    return net


def render_network(net, comments=()):
    """Write a network grouped by layer, so the text shows its parallel structure."""
    numbers, depth = net.layers()
    out = [f"# {c}" for c in comments]
    out.append(f"wires {net.wires}")
    for layer in range(1, depth + 1):
        out.append(f"# layer {layer}")
        out += [f"{i} {j}" for (i, j), k in zip(net.comps, numbers) if k == layer]
    return "\n".join(out) + "\n"


def _check_limit(max_exhaustive):
    if not 1 <= max_exhaustive <= 24:
        raise SortnetError("--max-exhaustive must be between 1 and 24")


def _input_bits(n, wire):
    """Bitset over all 2**n inputs: bit x is set when input x has a 1 on `wire`."""
    size = 1 << n
    half = 1 << wire
    period = half << 1
    block = ((1 << half) - 1) << half
    return block * (((1 << size) - 1) // ((1 << period) - 1))


def _exhaustive_state(n):
    return [_input_bits(n, w) for w in range(n)]


def _run_bits(comps, state):
    state = list(state)
    for i, j in comps:
        a, b = state[i], state[j]
        state[i] = a & b
        state[j] = a | b
    return state


def _unsorted_mask(state):
    """Bitset of inputs whose output is not non-decreasing across the wires."""
    mask = 0
    for k in range(len(state) - 1):
        mask |= state[k] & ~state[k + 1]
    return mask


def _apply_list(comps, values):
    values = list(values)
    for i, j in comps:
        if values[j] < values[i]:
            values[i], values[j] = values[j], values[i]
    return values


def _sorts_exhaustive(n, comps):
    return _unsorted_mask(_run_bits(comps, _exhaustive_state(n))) == 0


def check_network(net, max_exhaustive=DEFAULT_MAX_EXHAUSTIVE,
                  samples=DEFAULT_SAMPLES, seed=DEFAULT_SEED):
    """Check that the network sorts. Exhaustive when small enough, sampled otherwise."""
    _check_limit(max_exhaustive)
    n = net.wires
    if n <= max_exhaustive:
        method, count = "exhaustive", 1 << n
        state = _exhaustive_state(n)
    else:
        if samples < 1:
            raise SortnetError("--samples must be at least 1")
        method, count = "sampled", samples
        rng = random.Random(seed)
        state = [rng.getrandbits(samples) for _ in range(n)]
    bad = _unsorted_mask(_run_bits(net.comps, state))
    result = {
        "wires": n,
        "method": method,
        "inputs": count,
        "failures": bin(bad).count("1"),
        "sorts": bad == 0,
        "example": None,
    }
    if bad:
        x = (bad & -bad).bit_length() - 1
        vec = [(state[w] >> x) & 1 for w in range(n)]
        result["example"] = {"input": vec, "output": _apply_list(net.comps, vec)}
    return result


def never_swapping(net):
    """Indices of comparators that never exchange values on any 0-1 input (exhaustive)."""
    state = _exhaustive_state(net.wires)
    dead = []
    for k, (i, j) in enumerate(net.comps):
        a, b = state[i], state[j]
        if a & ~b == 0:
            dead.append(k)
        state[i] = a & b
        state[j] = a | b
    return dead


def prune_network(net, max_exhaustive=DEFAULT_MAX_EXHAUSTIVE):
    """Drop comparators that do nothing, then greedily drop any whose removal still sorts."""
    _check_limit(max_exhaustive)
    if net.wires > max_exhaustive:
        raise SortnetError(f"prune needs an exhaustive check, so wires must be at most {max_exhaustive}")
    if not _sorts_exhaustive(net.wires, net.comps):
        raise SortnetError("network does not sort, so nothing can be pruned safely")
    dead = set(never_swapping(net))
    removed = [net.lines[k] for k in sorted(dead)]
    items = [(c, l) for k, (c, l) in enumerate(zip(net.comps, net.lines)) if k not in dead]
    k = 0
    while k < len(items):
        trial = [c for c, _ in items[:k] + items[k + 1:]]
        if _sorts_exhaustive(net.wires, trial):
            removed.append(items[k][1])
            del items[k]
        else:
            k += 1
    pruned = Network(net.wires, [c for c, _ in items], [l for _, l in items])
    return pruned, sorted(removed)


def compare_networks(a, b, max_exhaustive=DEFAULT_MAX_EXHAUSTIVE):
    """Exact equivalence: two comparator networks are equal iff they agree on all 0-1 inputs."""
    if a.wires != b.wires:
        raise SortnetError(f"networks have different widths ({a.wires} and {b.wires} wires)")
    _check_limit(max_exhaustive)
    n = a.wires
    if n > max_exhaustive:
        raise SortnetError(f"compare needs an exhaustive check, so wires must be at most {max_exhaustive}")
    state = _exhaustive_state(n)
    out_a = _run_bits(a.comps, state)
    out_b = _run_bits(b.comps, state)
    diff = 0
    for x, y in zip(out_a, out_b):
        diff |= x ^ y
    depth_a = a.layers()[1]
    depth_b = b.layers()[1]
    result = {
        "wires": n,
        "a_comparators": len(a.comps),
        "b_comparators": len(b.comps),
        "a_depth": depth_a,
        "b_depth": depth_b,
        "a_sorts": _unsorted_mask(out_a) == 0,
        "b_sorts": _unsorted_mask(out_b) == 0,
        "equivalent": diff == 0,
        "example": None,
    }
    if diff:
        x = (diff & -diff).bit_length() - 1
        vec = [(x >> w) & 1 for w in range(n)]
        result["example"] = {
            "input": vec,
            "a_output": _apply_list(a.comps, vec),
            "b_output": _apply_list(b.comps, vec),
        }
    return result


def apply_network(net, values):
    """Run the network on real values. Returns (sorted values, snapshot after each layer)."""
    if len(values) != net.wires:
        raise SortnetError(f"network has {net.wires} wires but {len(values)} values were given")
    numbers, depth = net.layers()
    values = list(values)
    snapshots = [list(values)]
    for layer in range(1, depth + 1):
        for (i, j), k in zip(net.comps, numbers):
            if k == layer and values[j] < values[i]:
                values[i], values[j] = values[j], values[i]
        snapshots.append(list(values))
    return values, snapshots


def parse_value(token):
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            raise SortnetError(f"not a number: {token!r}")


def diagram(net):
    """ASCII picture: wires run left to right, 'o' marks a comparator end, '+' a crossing."""
    numbers, depth = net.layers()
    n = net.wires
    width = 3
    cols = max(depth, 1) * width
    rows = []
    for r in range(2 * n - 1):
        rows.append(["-" if r % 2 == 0 else " "] * cols)
    for (i, j), layer in zip(net.comps, numbers):
        x = (layer - 1) * width + 1
        for r in range(2 * i, 2 * j + 1):
            if r % 2 == 1:
                rows[r][x] = "|"
            elif r in (2 * i, 2 * j):
                rows[r][x] = "o"
            elif rows[r][x] != "o":
                rows[r][x] = "+"
    out = []
    for r, row in enumerate(rows):
        prefix = f"{r // 2:>3} " if r % 2 == 0 else "    "
        out.append(prefix + "".join(row))
    return "\n".join(out)


def generate_oddeven(n):
    """Batcher's odd-even merge sort for any width (comparators beyond the wires are never emitted)."""
    comps = []
    p = 1
    while p < n:
        k = p
        while k >= 1:
            for j in range(k % p, n - k, 2 * k):
                for i in range(min(k, n - j - k)):
                    if (i + j) // (2 * p) == (i + j + k) // (2 * p):
                        comps.append((i + j, i + j + k))
            k //= 2
        p *= 2
    return comps


def generate_transposition(n):
    """Odd-even transposition sort: n rounds of adjacent comparators."""
    comps = []
    for r in range(n):
        for i in range(r % 2, n - 1, 2):
            comps.append((i, i + 1))
    return comps


def network_lint(net, max_exhaustive):
    """Warnings for a network that parsed cleanly: reversed, dead and unused parts."""
    findings = []
    for (i, j), lineno in zip(net.comps, net.lines):
        if i > j:
            findings.append((lineno, "warning", f"comparator {i} {j} is high-to-low; the minimum goes to wire {i}"))
    if net.wires <= max_exhaustive:
        for k in never_swapping(net):
            i, j = net.comps[k]
            findings.append((net.lines[k], "warning", f"comparator {i} {j} never exchanges values and can be deleted"))
    touched = {w for c in net.comps for w in c}
    for w in range(net.wires):
        if w not in touched:
            findings.append((0, "warning", f"wire {w} is never compared"))
    return sorted(findings)


def network_stats(net, max_exhaustive, samples, seed):
    numbers, depth = net.layers()
    n = net.wires
    check = check_network(net, max_exhaustive, samples, seed)
    dead = len(never_swapping(net)) if n <= max_exhaustive else None
    stats = {
        "wires": n,
        "comparators": len(net.comps),
        "depth": depth,
        "depth_lower_bound": (n - 1).bit_length(),
        "never_swapping": dead,
        "sorts": check["sorts"],
        "check": check,
    }
    if n in BEST_KNOWN:
        stats["best_known_comparators"], stats["best_known_depth"] = BEST_KNOWN[n]
    return stats


def _describe_check(path, r):
    if r["method"] == "exhaustive":
        basis = f"exhaustive over all {r['inputs']} 0-1 inputs (a proof)"
    else:
        basis = f"{r['inputs']} random 0-1 inputs (sampled, not a proof)"
    if r["sorts"]:
        return f"OK {path}: {r['wires']} wires sort; checked {basis}"
    lines = [f"FAIL {path}: {r['wires']} wires do not sort; "
             f"{r['failures']} inputs left unsorted ({basis})"]
    ex = r["example"]
    lines.append(f"  example input  {ex['input']}")
    lines.append(f"  example output {ex['output']}")
    return "\n".join(lines)


def cmd_check(args):
    net = load_network(args.file)
    result = check_network(net, args.max_exhaustive, args.samples, args.seed)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_describe_check(args.file, result))
    return 0 if result["sorts"] else 1


def cmd_stats(args):
    net = load_network(args.file)
    s = network_stats(net, args.max_exhaustive, args.samples, args.seed)
    if args.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"file:               {args.file}")
    print(f"wires:              {s['wires']}")
    print(f"comparators:        {s['comparators']}")
    print(f"depth:              {s['depth']} (lower bound {s['depth_lower_bound']})")
    print(f"sorts:              {'yes' if s['sorts'] else 'no'} ({s['check']['method']})")
    if s["never_swapping"] is not None:
        print(f"never-swapping:     {s['never_swapping']}")
    if "best_known_comparators" in s:
        print(f"best known:         {s['best_known_comparators']} comparators, depth {s['best_known_depth']}")
    return 0 if s["sorts"] else 1


def cmd_lint(args):
    text = read_text(args.file)
    net, errors = parse_text(text)
    if errors:
        for ln, msg in errors:
            print(f"{args.file}:{ln}: error: {msg}")
        return 1
    if net.wires < 1:
        print(f"{args.file}: error: empty network")
        return 1
    findings = network_lint(net, args.max_exhaustive)
    if not findings:
        print(f"OK {args.file}: no findings")
        return 0
    for ln, sev, msg in findings:
        where = f"{args.file}:{ln}" if ln else args.file
        print(f"{where}: {sev}: {msg}")
    fail = args.strict or any(sev == "error" for _, sev, _ in findings)
    return 1 if fail else 0


def cmd_diagram(args):
    print(diagram(load_network(args.file)))
    return 0


def cmd_layers(args):
    net = load_network(args.file)
    numbers, depth = net.layers()
    for layer in range(1, depth + 1):
        pairs = [f"{i}-{j}" for (i, j), k in zip(net.comps, numbers) if k == layer]
        print(f"layer {layer}: " + "  ".join(pairs))
    return 0


def cmd_apply(args):
    net = load_network(args.file)
    values = [parse_value(t) for t in args.values]
    result, snapshots = apply_network(net, values)
    if args.trace:
        print("start:    " + " ".join(str(v) for v in snapshots[0]))
        for layer, snap in enumerate(snapshots[1:], start=1):
            print(f"layer {layer}:  " + " ".join(str(v) for v in snap))
    else:
        print(" ".join(str(v) for v in result))
    return 0


def cmd_prune(args):
    net = load_network(args.file)
    pruned, removed = prune_network(net, args.max_exhaustive)
    text = render_network(pruned, comments=[f"pruned from {args.file}"])
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"removed {len(removed)} comparators (source lines {removed}); "
              f"{len(net.comps)} -> {len(pruned.comps)} written to {args.output}")
    else:
        sys.stdout.write(text)
        print(f"# removed {len(removed)} comparators (source lines {removed})", file=sys.stderr)
    return 0


def cmd_generate(args):
    if args.n < 1:
        raise SortnetError("width must be at least 1")
    maker = generate_oddeven if args.method == "oddeven" else generate_transposition
    comps = maker(args.n)
    net = Network(args.n, comps, [0] * len(comps))
    text = render_network(net, comments=[f"{args.method} sorting network for {args.n} wires"])
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {len(comps)} comparators to {args.output}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_compare(args):
    a = load_network(args.file_a)
    b = load_network(args.file_b)
    r = compare_networks(a, b, args.max_exhaustive)
    print(f"{args.file_a}: {r['a_comparators']} comparators, depth {r['a_depth']}, "
          f"{'sorts' if r['a_sorts'] else 'does not sort'}")
    print(f"{args.file_b}: {r['b_comparators']} comparators, depth {r['b_depth']}, "
          f"{'sorts' if r['b_sorts'] else 'does not sort'}")
    if r["equivalent"]:
        print("equivalent: yes (identical outputs on every 0-1 input)")
    else:
        ex = r["example"]
        print("equivalent: no")
        print(f"  input    {ex['input']}")
        print(f"  first    {ex['a_output']}")
        print(f"  second   {ex['b_output']}")
    return 0 if r["equivalent"] else 1


def cmd_bounds(args):
    ns = [args.n] if args.n else sorted(BEST_KNOWN)
    print("wires  best-comparators  best-depth  depth-lower-bound")
    for n in ns:
        lower = (n - 1).bit_length() if n >= 1 else 0
        if n in BEST_KNOWN:
            size, depth = BEST_KNOWN[n]
            print(f"{n:>5}  {size:>16}  {depth:>10}  {lower:>17}")
        else:
            print(f"{n:>5}  no table entry (depth lower bound {lower})")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="sortnet", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def add_check_options(p):
        p.add_argument("--max-exhaustive", type=int, default=DEFAULT_MAX_EXHAUSTIVE,
                       help="check every 0-1 input up to this many wires (default %(default)s)")
        p.add_argument("--samples", type=int, default=DEFAULT_SAMPLES,
                       help="random 0-1 inputs used above the exhaustive limit (default %(default)s)")
        p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="sampling seed (default %(default)s)")

    p = sub.add_parser("check", help="verify that a network sorts")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    add_check_options(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("stats", help="size, depth, best-known comparison and dead comparators")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    add_check_options(p)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("lint", help="line-numbered errors and warnings")
    p.add_argument("file")
    p.add_argument("--strict", action="store_true", help="treat warnings as failures")
    p.add_argument("--max-exhaustive", type=int, default=DEFAULT_MAX_EXHAUSTIVE)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("diagram", help="ASCII picture of the network")
    p.add_argument("file")
    p.set_defaults(func=cmd_diagram)

    p = sub.add_parser("layers", help="list the parallel layers")
    p.add_argument("file")
    p.set_defaults(func=cmd_layers)

    p = sub.add_parser("apply", help="sort a list of numbers with the network")
    p.add_argument("file")
    p.add_argument("values", nargs="+")
    p.add_argument("--trace", action="store_true", help="show the list after each layer")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("prune", help="remove redundant comparators that keep it sorting")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="write here instead of stdout")
    p.add_argument("--max-exhaustive", type=int, default=DEFAULT_MAX_EXHAUSTIVE)
    p.set_defaults(func=cmd_prune)

    p = sub.add_parser("generate", help="write a sorting network for N wires")
    p.add_argument("method", choices=["oddeven", "transposition"])
    p.add_argument("n", type=int)
    p.add_argument("-o", "--output", help="write here instead of stdout")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("compare", help="check two networks are exactly equivalent")
    p.add_argument("file_a")
    p.add_argument("file_b")
    p.add_argument("--max-exhaustive", type=int, default=DEFAULT_MAX_EXHAUSTIVE)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("bounds", help="best-known sizes and depths for small widths")
    p.add_argument("n", type=int, nargs="?")
    p.set_defaults(func=cmd_bounds)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SortnetError as exc:
        print(f"sortnet: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
