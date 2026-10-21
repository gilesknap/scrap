"""A task box ticked on a page is an edit on the revision shown (tasks.ts)."""


def test_a_tick_on_a_stale_revision_is_refused_and_overwrites_nothing(client, note):
    ref = note("Jobs\n\n- [ ] milk\n- [ ] milk")
    url = f"/api/pages/{ref['page_id']}"
    ticked = client.patch(
        url, json={"base_rev": 1, "body": "Jobs\n\n- [ ] milk\n- [x] milk"}
    )
    assert ticked.status_code == 200 and ticked.json()["rev"] == 2
    # Another device's tick, made on revision 1 too: refused with the current revision
    stale = client.patch(
        url, json={"base_rev": 1, "body": "Jobs\n\n- [x] milk\n- [ ] milk"}
    )
    assert stale.status_code == 409
    page = client.get(url).json()
    assert (page["rev"], page["body"]) == (2, "Jobs\n\n- [ ] milk\n- [x] milk")
