from pathlib import Path

import pytest

import sortnet as sn

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def net_from_text(text):
    net, errors = sn.parse_text(text)
    assert errors == []
    return net


def test_parse_reads_width_and_comparators():
    net = net_from_text("# header\nwires 4\n0 1\n2,3\n")
    assert net.wires == 4
    assert net.comps == [(0, 1), (2, 3)]
    assert net.lines == [3, 4]


def test_parse_infers_width_when_not_declared():
    assert net_from_text("0 2\n1 3\n").wires == 4


def test_parse_reports_each_bad_line_with_its_number():
    _, errors = sn.parse_text("wires 4\n0 1\n1 1\n0 9\n2 3 extra\n")
    assert [line for line, _ in errors] == [3, 4, 5]
    assert "itself" in errors[0][1]
    assert "outside 0..3" in errors[1][1]


def test_input_bits_match_the_definition():
    for n in range(1, 6):
        for wire in range(n):
            expected = sum(1 << x for x in range(1 << n) if (x >> wire) & 1)
            assert sn._input_bits(n, wire) == expected


def test_optimal_four_wire_network_is_proved_to_sort():
    net = sn.load_network(EXAMPLES / "net4.txt")
    result = sn.check_network(net)
    assert result["sorts"] is True
    assert result["method"] == "exhaustive"
    assert result["inputs"] == 16


def test_failing_network_gives_a_counterexample():
    result = sn.check_network(sn.load_network(EXAMPLES / "fail3.txt"))
    assert result["sorts"] is False
    assert result["failures"] == 1
    assert result["example"] == {"input": [1, 1, 0], "output": [1, 0, 1]}


def test_generated_networks_sort_for_small_widths():
    for n in range(1, 13):
        net = sn.Network(n, sn.generate_oddeven(n), [0] * len(sn.generate_oddeven(n)))
        assert sn.check_network(net)["sorts"], f"oddeven fails at n={n}"
    for n in range(1, 11):
        comps = sn.generate_transposition(n)
        assert sn.check_network(sn.Network(n, comps, [0] * len(comps)))["sorts"]


def test_batcher_sizes_match_known_values():
    assert len(sn.generate_oddeven(4)) == 5
    assert len(sn.generate_oddeven(8)) == 19


def test_layers_are_disjoint_and_depth_is_correct():
    net = sn.load_network(EXAMPLES / "net4.txt")
    numbers, depth = net.layers()
    assert depth == 3
    for layer in range(1, depth + 1):
        wires = [w for (c, k) in zip(net.comps, numbers) if k == layer for w in c]
        assert len(wires) == len(set(wires))


def test_never_swapping_finds_a_repeated_comparator():
    net = sn.Network(2, [(0, 1), (0, 1)], [1, 2])
    assert sn.never_swapping(net) == [1]


def test_prune_removes_dead_comparator_and_keeps_sorting():
    net = net_from_text(
        "wires 4\n0 1\n2 3\n0 2\n1 3\n1 2\n0 1\n"
    )
    pruned, removed = sn.prune_network(net)
    assert removed == [7]
    assert len(pruned.comps) == 5
    assert sn._sorts_exhaustive(4, pruned.comps)


def test_prune_refuses_a_network_that_does_not_sort():
    with pytest.raises(sn.SortnetError, match="does not sort"):
        sn.prune_network(sn.load_network(EXAMPLES / "fail3.txt"))


def test_compare_finds_two_sorting_networks_equivalent():
    a = sn.load_network(EXAMPLES / "net4.txt")
    comps = sn.generate_oddeven(4)
    b = sn.Network(4, comps, [0] * len(comps))
    assert sn.compare_networks(a, b)["equivalent"] is True


def test_compare_reports_a_differing_input():
    a = sn.load_network(EXAMPLES / "fail3.txt")
    comps = sn.generate_oddeven(3)
    b = sn.Network(3, comps, [0] * len(comps))
    result = sn.compare_networks(a, b)
    assert result["equivalent"] is False
    assert result["example"]["input"] == [1, 1, 0]


def test_apply_sorts_numbers_and_traces_each_layer():
    net = sn.load_network(EXAMPLES / "net4.txt")
    result, snapshots = sn.apply_network(net, [4, 3, 2, 1])
    assert result == [1, 2, 3, 4]
    assert len(snapshots) == 4
    assert snapshots[0] == [4, 3, 2, 1]


def test_apply_handles_mixed_int_and_float_values():
    net = sn.load_network(EXAMPLES / "net4.txt")
    values = [sn.parse_value(t) for t in ["2.5", "1", "3", "-0.5"]]
    result, _ = sn.apply_network(net, values)
    assert result == [-0.5, 1, 2.5, 3]


def test_diagram_has_one_row_per_wire_and_two_marks_per_comparator():
    net = sn.load_network(EXAMPLES / "net4.txt")
    rows = sn.diagram(net).split("\n")
    assert len(rows) == 2 * 4 - 1
    assert "".join(rows).count("o") == 2 * len(net.comps)


def test_render_round_trips_through_the_parser():
    comps = sn.generate_oddeven(6)
    text = sn.render_network(sn.Network(6, comps, [0] * len(comps)))
    back = net_from_text(text)
    assert sorted(back.comps) == sorted(comps)
    assert sn.check_network(back)["sorts"]


def test_sampled_mode_is_used_above_the_exhaustive_limit():
    comps = sn.generate_oddeven(24)
    result = sn.check_network(sn.Network(24, comps, [0] * len(comps)),
                              max_exhaustive=20, samples=512, seed=1)
    assert result["method"] == "sampled"
    assert result["inputs"] == 512
    assert result["sorts"] is True


def test_lint_warns_about_reversed_and_unused_wires():
    net = net_from_text("wires 4\n1 0\n")
    messages = [msg for _, sev, msg in sn.network_lint(net, 20) if sev == "warning"]
    assert any("high-to-low" in m for m in messages)
    assert any("wire 2 is never compared" in m for m in messages)


def test_bounds_table_lists_known_values():
    assert sn.BEST_KNOWN[8] == (19, 6)
    assert sn.main(["bounds", "4"]) == 0


def test_cli_exit_codes(tmp_path):
    assert sn.main(["check", str(EXAMPLES / "net4.txt")]) == 0
    assert sn.main(["check", str(EXAMPLES / "fail3.txt")]) == 1
    assert sn.main(["lint", str(EXAMPLES / "messy.txt")]) == 1
    assert sn.main(["check", str(tmp_path / "missing.txt")]) == 2


def test_generate_then_check_from_the_command_line(tmp_path):
    out = tmp_path / "oe10.txt"
    assert sn.main(["generate", "oddeven", "10", "-o", str(out)]) == 0
    assert sn.main(["check", str(out)]) == 0
