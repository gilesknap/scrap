"""Snooze was retired (28 Oct 2026): an old client's `snoozed_until` is ignored, never a 500."""

from scrap.store import new_ulid


def test_capture_and_patch_ignore_snoozed_until(client):
    made = client.post(
        "/api/captures",
        json={
            "id": new_ulid(),
            "text": "water plants",
            "kind": "todo",
            "due": "2026-11-01",
            "snoozed_until": "2026-12-01",
        },
    )
    assert made.status_code == 201
    key = made.json()["page_id"]
    patched = client.patch(
        f"/api/pages/{key}", json={"due": "2026-11-02", "snoozed_until": "2026-12-02"}
    )
    assert patched.status_code == 200
    page = patched.json()
    assert page["due"] == "2026-11-02"
    assert "snoozed_until" not in page
