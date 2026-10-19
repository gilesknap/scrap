import json
import math

import pytest

from scrap.sanitise import model_output, scene, scene_text
from scrap.store import InvalidError

W, H = 2048, 1536


def out(*elements, **fields):
    raw = {"kind": "whiteboard", "title": " A\x00 board ", "tags": [], "text": "t",
           "description": "d", "elements": list(elements), **fields}  # fmt: skip
    return model_output(raw, W, H)


def test_model_elements_become_skeletons():
    got = out(
        {"type": "rectangle", "id": "a", "x": 10, "y": 10, "width": 100, "height": 50,
         "label": "Read config", "labelFontSize": 28, "strokeColor": "#1E1E1E"},
        {"type": "ellipse", "id": "b", "x": 300, "y": 10, "width": 100, "height": 50},
        {"type": "arrow", "x": 110, "y": 35, "points": [0, 0, 95, 0, 190, 0],
         "start": "a", "end": "b", "label": "yes", "startArrowhead": "arrow"},
        {"type": "text", "id": "n", "x": 10, "y": 200, "text": "note", "fontSize": 24},
        {"type": "line", "x": 10, "y": 230, "points": [0, 0, 50, 0]},
    )  # fmt: skip
    assert got["title"] == "A board" and got["warnings"] == []
    shape, _, arrow, text, line = got["elements"]
    assert shape["label"] == {"text": "Read config", "fontSize": 28}
    assert shape["strokeColor"] == "#1e1e1e"
    assert arrow["points"] == [[0, 0], [95, 0], [190, 0]]
    assert (arrow["start"], arrow["end"]) == ({"id": "a"}, {"id": "b"})
    assert arrow["label"]["text"] == "yes" and arrow["startArrowhead"] == "arrow"
    assert text == {"type": "text", "x": 10, "y": 200, "id": "n", "text": "note",
                    "fontSize": 24}  # fmt: skip
    assert line["points"] == [[0, 0], [50, 0]]


@pytest.mark.parametrize(
    "element",
    [
        {"type": "image", "x": 0, "y": 0},
        {"type": "text", "x": 0, "y": 0, "text": "  "},
        {"type": "text", "x": -W, "y": 0, "text": "far off"},
        {"type": "text", "x": math.inf, "y": 0, "text": "x"},
        {"type": "text", "x": True, "y": 0, "text": "x"},
        {"type": "text", "x": 0, "y": 0, "text": "x", "id": "bad id!"},
        {"type": "text", "x": 0, "y": 0, "text": "x", "id": "a" * 33},
        {"type": "text", "x": 0, "y": 0, "text": "x", "strokeColor": "red"},
        {"type": "text", "x": 0, "y": 0, "text": "x", "fontSize": 3},
        {"type": "text", "x": 0, "y": 0, "text": "x" * 2001},
        {"type": "rectangle", "x": 0, "y": 0, "width": -1, "height": 5},
        {"type": "rectangle", "x": 0, "y": 0, "width": W * 2, "height": 5},
        {"type": "arrow", "x": 0, "y": 0},
        {"type": "arrow", "x": 0, "y": 0, "points": [0, 0, 5]},
        {"type": "arrow", "x": 0, "y": 0, "points": [1, 1, 5, 5]},
        {"type": "line", "x": 0, "y": 0, "points": [0, 0] * 201},
        {"type": "line", "x": 0, "y": 0, "points": [0, 0, 0, H * 2]},
    ],
)
def test_a_bad_model_element_is_dropped_with_a_warning(element):
    good = {"type": "text", "x": 1, "y": 1, "text": "kept"}
    got = out(good, element)
    assert got["elements"] == [{**good, "fontSize": 20}]
    assert got["warnings"][0].startswith("element 1 dropped")


def test_bindings_to_dropped_elements_are_removed():
    got = out(
        {"type": "rectangle", "id": "a", "x": 0, "y": 0, "width": 9, "height": 9},
        {"type": "rectangle", "id": "a", "x": 50, "y": 0, "width": 9, "height": 9},
        {"type": "arrow", "x": 9, "y": 5, "points": [0, 0, 40, 0], "start": "a",
         "end": "zz"},
    )  # fmt: skip
    arrow = got["elements"][1]
    assert arrow["start"] == {"id": "a"} and "end" not in arrow
    assert got["warnings"] == ["element 1 dropped: duplicate id",
                               "element 1: end names no element, unbound"]  # fmt: skip


def test_fields_are_cleaned_and_limits_kept():
    line = {"type": "line", "x": 0, "y": 0, "points": [0, 0, 1, 1]}
    tags = ["Kafka", "kafka", " Message  Queue ", "", 7]
    got = out(*[line] * 1001, tags=tags, kind="weird")
    assert len(got["elements"]) == 1000 and "1 elements over" in got["warnings"][0]
    assert got["tags"] == ["kafka", "message-queue"] and got["kind"] == "other"


def test_no_text_and_no_description_is_invalid():
    with pytest.raises(ValueError):
        out(text="", description="")


def test_bad_elements_never_cost_the_text():
    got = out({"type": "image", "x": 0, "y": 0}, {"type": "text", "x": 0, "y": 0})
    assert (got["text"], got["elements"], len(got["warnings"])) == ("t", [], 2)


# ---- human scenes, from the editor

SCENE = {
    "type": "excalidraw",
    "width": 2048,
    "height": 1536,
    "elements": [
        {"type": "rectangle", "id": "r", "x": -5000, "y": 1e6, "width": 10,
         "height": 10, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
         "index": "a0", "groupIds": ["g"],
         "boundElements": [{"id": "t", "type": "text"}]},
        {"type": "text", "id": "t", "x": 0, "y": 0, "text": "Hello", "originalText":
         "Hello", "containerId": "r", "strokeColor": "rgba(0, 0, 0, 0.5)"},
        {"type": "freedraw", "id": "f", "x": 0, "y": 0, "points": [[0, 0]] * 50_000,
         "pressures": [0.5] * 10, "strokeColor": "#abc"},
        {"type": "arrow", "id": "a", "x": 0, "y": 0, "points": [[0, 0], [5, 5]],
         "link": "https://example.com", "startBinding": {"elementId": "r"},
         "customData": {"any": ["thing"]}},
        {"type": "text", "id": "u", "x": 0, "y": 0, "text": "World",
         "strokeColor": "#1e1e1e80"},
        {"type": "text", "id": "gone", "x": 0, "y": 0, "text": "Deleted",
         "isDeleted": True},
    ],
    "appState": {"viewBackgroundColor": "#ffffff", "zoom": {"value": 3}},
    "files": {"abc": {"dataURL": "data:image/png;base64,AAAA"}},
}  # fmt: skip


def test_a_human_scene_is_kept_with_files_stripped():
    got = scene(SCENE)
    assert got["elements"] == SCENE["elements"] and "files" not in got
    assert got["appState"] == {"viewBackgroundColor": "#ffffff"}
    assert (got["format"], got["width"], got["height"]) == ("scene", 2048, 1536)
    assert scene_text(got) == "Hello\nWorld"


@pytest.mark.parametrize(
    "change",
    [
        {"type": "image"},
        {"type": "embeddable"},
        {"type": "iframe"},
        {"type": "frame"},
        {"type": "magicframe"},
        {"type": ["arrow"]},
        {"x": "NaN"},
        {"x": math.nan},
        {"y": math.inf},
        {"angle": -math.inf},
        {"pressures": [math.nan]},  # issue #19: fields the checks do not list
        {"roundness": {"value": math.inf}},
        {"customData": {"n": math.nan}},
        {"lastCommittedPoint": [math.nan, 0]},
        {"strokeColor": "url(javascript:alert(1))"},
        {"backgroundColor": "red; background: url(x)"},
        {"link": "javascript:alert(1)"},
        {"link": "data:text/html,hi"},
        {"link": 5},
        {"points": [[0, 0]] * 201},
        {"points": [[0, "x"]]},
        {"points": [[0, 1e400]]},
        {"points": "nope"},
        {"text": 5},
        {"id": {"$gt": ""}},
    ],
)
def test_a_bad_human_scene_is_refused(change):
    bad = json.loads(json.dumps(SCENE))
    bad["elements"][3].update(change)
    with pytest.raises(InvalidError):
        scene(bad)


def test_huge_but_finite_scenes_are_kept_up_to_5_mb():
    many = [{"type": "rectangle", "id": f"r{n}", "x": n * 1e12, "y": -1e300,
             "width": 1, "height": 1} for n in range(5000)]  # fmt: skip
    assert len(scene({"elements": many})["elements"]) == 5000
    big = {"elements": [{"type": "text", "x": 0, "y": 0, "text": "x" * 6_000_000}]}
    with pytest.raises(InvalidError, match="5 MB"):
        scene(big)
    files = {"elements": [], "files": {"f": "x" * 6_000_000}}  # stripped first
    assert scene(files)["elements"] == []
    for shape in ({"elements": "nope"}, [], None, {"elements": [None]}):
        with pytest.raises(InvalidError):
            scene(shape)
    assert "width" not in scene({"elements": [], "width": -1, "height": 0})
    assert "appState" not in scene({"elements": [], "appState": ["x"]})
