"""The Claude call (with the SDK client faked), its error classes and the sent JPEG."""

import io
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from PIL import Image

from scrap import claude, preview
from scrap.store import Store

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(code, message, headers=None, details=None):
    error = {"type": "error_type", "message": message}
    if details:
        error["details"] = details
    body = {"type": "error", "error": error}
    response = httpx2.Response(code, request=REQUEST, headers=headers or {}, json=body)
    return anthropic.APIStatusError(message, response=response, body=body)


SPEND_LIMIT = (
    "You have reached your specified workspace API usage limits. You will regain"
    " access on 2026-11-01 at 00:00 UTC."
)


@pytest.mark.parametrize(
    "error, cls, retry_after",
    [
        (status_error(402, "billing problem"), "credit", None),
        (status_error(400, SPEND_LIMIT), "credit", None),
        (status_error(400, "Your credit balance is too low"), "credit", None),
        (
            status_error(
                429, "limit", details={"error_code": "enforced_spend_limit_reached"}
            ),
            "credit",
            None,
        ),
        (status_error(401, "invalid x-api-key"), "auth", None),
        (status_error(403, "forbidden"), "auth", None),
        (status_error(404, "model: claude-nope"), "auth", None),
        (status_error(429, "rate limited", {"retry-after": "17"}), "outage", 17.0),
        (status_error(429, "rate limited"), "outage", None),
        (status_error(500, "api error"), "outage", None),
        (status_error(504, "gateway"), "outage", None),
        (status_error(529, "overloaded", {"retry-after": "5"}), "outage", 5.0),
        (anthropic.APIConnectionError(request=REQUEST), "outage", None),
        (anthropic.APITimeoutError(request=REQUEST), "timeout", None),
        (status_error(400, "image could not be processed"), "content", None),
        (status_error(409, "conflict"), "content", None),
        (status_error(413, "too large"), "content", None),
        (status_error(422, "unprocessable"), "content", None),
        (ValueError("a bug"), "internal", None),
    ],
)
def test_error_classes(error, cls, retry_after):
    got = claude.classify(error)
    assert (got.cls, got.retry_after) == (cls, retry_after)


class FakeMessages:
    def __init__(self, result):
        self.result, self.sent = result, {}

    def create(self, **kwargs):
        self.sent = kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def response(text, stop_reason="end_turn"):
    block = SimpleNamespace(model_dump=lambda mode: {"type": "text", "text": text})
    usage = SimpleNamespace(model_dump=lambda mode: {"input_tokens": 1})
    return SimpleNamespace(
        content=[block], usage=usage, model="served", stop_reason=stop_reason
    )


@pytest.fixture
def fake(monkeypatch):
    def install(result):
        messages = FakeMessages(result)
        monkeypatch.setattr(claude, "_client", SimpleNamespace(messages=messages))
        return messages

    return install


MESSAGES = [
    {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {"type": "blob", "sha256": "f" * 64},
                "transformations": {"oversized_image": "error"},
            },
            {"type": "text", "text": "The image is 2x1 pixels."},
        ],
    }
]


def call():
    return claude.complete(
        "claude-opus-5-5",
        "system",
        MESSAGES,
        claude.SCHEMA,
        lambda sha: (b"jpg", "image/jpeg"),
    )


def test_complete_sends_one_call_and_returns_the_output(fake):
    messages = fake(response('{"kind": "photo"}'))
    done = call()
    assert done.output == {"kind": "photo"} and done.served_model == "served"
    sent = messages.sent
    assert (
        sent["max_tokens"] == 16000 and "tools" not in sent and "thinking" not in sent
    )
    assert sent["output_config"]["effort"] == "medium"
    assert sent["output_config"]["format"]["schema"] is claude.SCHEMA
    image = sent["messages"][0]["content"][0]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": "anBn",
    }
    assert image["transformations"] == {"oversized_image": "error"}
    assert MESSAGES[0]["content"][0]["source"]["type"] == "blob"  # stored form kept


@pytest.mark.parametrize(
    "result, cls",
    [
        (response("{}", "refusal"), "content"),
        (response('{"kind": "pho', "max_tokens"), "invalid"),
        (response("not json"), "invalid"),
        (response("[1]"), "invalid"),
        (anthropic.APITimeoutError(request=REQUEST), "timeout"),
        (status_error(529, "overloaded"), "outage"),
    ],
)
def test_complete_failures(fake, result, cls):
    fake(result)
    with pytest.raises(claude.CallError) as error:
        call()
    assert error.value.cls == cls


def test_the_client_never_retries_and_times_out_at_240_s(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(claude, "_client", None)
    client = claude.client()
    assert client.max_retries == 0 and client.timeout == 240
    assert claude.client() is client


def test_cost():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_read_input_tokens": 1_000_000}  # fmt: skip
    assert claude.cost_microusd("claude-opus-5-5", usage) == 6_200_000
    assert claude.cost_microusd("claude-unknown", usage) > 6_200_000


def test_schema_keeps_to_the_structured_output_subset():
    element = claude.SCHEMA["properties"]["elements"]["items"]
    optional = set(element["properties"]) - set(element["required"])
    assert len(optional) == 12
    text = json.dumps(claude.SCHEMA)
    for bound in ("minimum", "maximum", "minLength", "maxLength", "anyOf", "oneOf"):
        assert bound not in text


@pytest.mark.parametrize(
    "size, sent",
    [
        ((4032, 3024), (2048, 1536)),  # 4:3: 74 x 55 = 4070 tokens
        ((3024, 4032), (1536, 2048)),
        ((4000, 4000), (1932, 1932)),  # square: 69 x 69 = 4761
        ((800, 600), (800, 600)),  # never enlarged
        ((8000, 1000), (2048, 256)),
    ],
)
def test_claude_size(size, sent):
    w, h = preview.claude_size(*size)
    assert (w, h) == sent
    assert -(-w // 28) * -(-h // 28) <= 4784


def stored(tmp_path, data):
    store = Store(tmp_path)
    store.migrate()
    sha, size = store.put_blob(io.BytesIO(data))
    with store.connect() as conn:
        conn.execute("INSERT INTO blob VALUES (?, 'image/jpeg', ?, 'x')", (sha, size))
    return store, sha


def test_the_sent_jpeg_is_upright_and_within_the_caps(tmp_path):
    im = Image.new("RGB", (4000, 3000), "red")
    exif = Image.Exif()
    exif[0x0112] = 6  # held on its side
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif)
    store, sha = stored(tmp_path, out.getvalue())
    data, w, h = preview.for_claude(store, sha)
    sent = Image.open(io.BytesIO(data))
    assert (sent.format, sent.size, (w, h)) == ("JPEG", (1536, 2048), (1536, 2048))
    assert not sent.getexif()


def test_heic_is_converted(tmp_path):
    out = io.BytesIO()
    Image.new("RGB", (300, 200), "blue").save(out, "HEIF")
    store, sha = stored(tmp_path, out.getvalue())
    data, w, h = preview.for_claude(store, sha)
    assert Image.open(io.BytesIO(data)).format == "JPEG" and (w, h) == (300, 200)
