from kat import cfgnode


def test_nested_nodes_and_repeated_keys():
    root = cfgnode.loads("""
PART
{
    name = a // comment
    tag = x
    tag = y
    MODULE { name = M1 }
    MODULE
    {
        name = M2
    }
}
""")
    part = root.node("PART")
    assert part.get("name") == "a"
    assert part.get_all("tag") == ["x", "y"]
    assert [m.get("name") for m in part.nodes_named("MODULE")] == ["M1", "M2"]


def test_bom_crlf_and_top_level_values():
    root = cfgnode.loads("﻿ship = R\r\nPART\r\n{\r\n\tpart = p_1\r\n}\r\n")
    assert root.get("ship") == "R"
    assert root.node("PART").get("part") == "p_1"


def test_value_with_equals_and_empty_value():
    root = cfgnode.loads("a = b = c\nempty =\n")
    assert root.get("a") == "b = c"
    assert root.get("empty") == ""


def test_patch_node_names_and_stray_brace():
    root = cfgnode.loads("@PART[x]:NEEDS[Y]:FINAL { @title = T }\n}\nNODE { k = v }")
    assert [n.name for n in root.nodes] == ["@PART[x]:NEEDS[Y]:FINAL", "NODE"]


def test_walk_visits_all():
    root = cfgnode.loads("A { B { C { } } }")
    assert [n.name for n in root.walk()] == ["", "A", "B", "C"]


def test_ckan_progress_filter():
    from kat.ckan import _PROGRESS
    raw = ("Removing X...\n40.7 MiB/sec - 133.3 MiB (3 sec) left - 78%           \n"
           "69.2 MiB left - 0%           68.4 MiB left - 1%           \nFinished removing X\n")
    assert _PROGRESS.sub("", raw) == "Removing X...\nFinished removing X\n"
