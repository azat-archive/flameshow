import json
from flameshow.pprof_parser.parser import ProfileParser, Frame
from flameshow.pprof_parser import parse_golang_profile


def test_parse_sample_location_with_multiple_lines(data_dir):
    parser = ProfileParser("abc")
    with open(data_dir / "sample_location_line_multiple.json") as f:
        content = json.load(f)

    profile = parser.parse(content)
    root = profile.root_stack

    names = []
    while root.children:
        c0 = root.children[0]
        names.append(c0.name)
        root = c0

    assert names == [
        "github.com/prometheus/node_exporter/collector.NodeCollector.Collect.func1",
        "github.com/prometheus/node_exporter/collector.execute",
        "github.com/prometheus/node_exporter/collector.(*meminfoCollector).Update",
        "github.com/prometheus/node_exporter/collector.(*meminfoCollector).getMemInfo",
        "github.com/prometheus/node_exporter/collector.procFilePath",
        "path/filepath.Join",
        "path/filepath.join",
        "strings.Join",
        "strings.(*Builder).Grow",
        "strings.(*Builder).grow",
        "runtime.makeslice",
        "runtime.newstack",
        "runtime.copystack",
        "runtime.gentraceback",
    ]


def test_parse_max_depth_when_have_multiple_lines(data_dir):
    parser = ProfileParser("abc")
    with open(data_dir / "profile10s_node_exporter.json") as f:
        content = json.load(f)

    profile = parser.parse(content)
    assert profile.highest_lines == 26


def test_pile_up():
    root = Frame("root", 0, values=[5])
    s1 = Frame("s1", 1, values=[4], parent=root)
    s2 = Frame("s2", 2, values=[4], parent=s1)

    root.children = [s1]
    s1.children = [s2]

    s1 = Frame("s1", 3, values=[3], parent=None)
    s2 = Frame("s2", 4, values=[2], parent=s1)
    s1.children = [s2]

    root.pile_up(s1)
    assert root.children[0].values == [7]
    assert root.children[0].children[0].values == [6]


def test_render_detail_when_parent_zero():
    root = Frame("root", 0, values=[0])
    s1 = Frame("s1", 1, values=[0], parent=root, root=root)
    s1.line.function_name = "asdf"

    detail = s1.render_detail(0, "bytes")
    assert "(0.0% of parent, 0.0% of root)" in detail


def test_parse_to_json(data_dir):
    with open(data_dir / "profile-10seconds.out", "rb") as f:
        content = f.read()

    loaded_json = parse_golang_profile(content)

    with open(data_dir / "profile10s_node_exporter.json") as f:
        expected_json = json.load(f)

    assert loaded_json == expected_json
