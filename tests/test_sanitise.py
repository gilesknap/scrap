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


@pytest.mark.parametrize(
    "fields",
    [
        {"text": "", "description": ""},
        {"elements": [{"type": "image", "x": 0, "y": 0}]},  # nothing valid left
    ],
)
def test_nothing_usable_is_invalid(fields):
    with pytest.raises(ValueError):
        out(**fields)


SCENE = {
    "type": "excalidraw",
    "elements": [
        {"type": "rectangle", "id": "r", "x": -5000, "y": 1e6, "width": 10,
         "height": 10, "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
         "index": "a0", "groupIds": ["g"],
         "boundElements": [{"id": "t", "type": "text"}]},
        {"type": "text", "id": "t", "x": 0, "y": 0, "text": "Hello", "originalText":
         "Hello", "containerId": "r", "strokeColor": "rgba(0, 0, 0, 0.5)"},
        {"type": "freedraw", "id": "f", "x": 0, "y": 0, "points": [[0, 0]] * 50_000,
         "strokeColor": "#abc"},
        {"type": "arrow", "id": "a", "x": 0, "y": 0, "points": [[0, 0], [5, 5]],
         "link": "https://example.com", "startBinding": {"elementId": "r"}},
        {"type": "text", "id": "u", "x": 0, "y": 0, "text": "World",
         "strokeColor": "#1e1e1e80"},
    ],
    "appState": {"viewBackgroundColor": "#ffffff", "zoom": {"value": 3}},
    "files": {"abc": {"dataURL": "data:image/png;base64,AAAA"}},
}  # fmt: skip


def test_a_human_scene_is_kept_with_files_stripped():
    got = scene(SCENE)
    assert got["elements"] == SCENE["elements"] and "files" not in got
    assert got["appState"] == {"viewBackgroundColor": "#ffffff"}
    assert scene_text(got) == "Hello\nWorld"


@pytest.mark.parametrize(
    "change",
    [
        {"type": "image"},
        {"type": "embeddable"},
        {"type": "frame"},
        {"x": "NaN"},
        {"x": math.nan},
        {"strokeColor": "url(javascript:alert(1))"},
        {"link": "javascript:alert(1)"},
        {"points": [[0, 0]] * 201},
        {"points": [[0, "x"]]},
        {"text": 5},
    ],
)
def test_a_bad_human_scene_is_refused(change):
    bad = json.loads(json.dumps(SCENE))
    bad["elements"][3].update(change)
    with pytest.raises(InvalidError):
        scene(bad)


def test_a_scene_over_5_mb_is_refused():
    big = {"elements": [{"type": "text", "x": 0, "y": 0, "text": "x" * 6_000_000}]}
    with pytest.raises(InvalidError, match="5 MB"):
        scene(big)
    with pytest.raises(InvalidError):
        scene({"elements": "nope"})
