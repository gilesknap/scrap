import math

import pytest

from scrap.sanitise import model_output

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
