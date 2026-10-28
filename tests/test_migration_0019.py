"""0019: generated content keeps only its current version (ADR 39). An 18-store with
write-up and reading history migrates to one write-up per page and current readings,
and a drawing's history stays."""

from contextlib import closing

from scrap.store.db import connect, create_baseline, migrate

T = "2026-01-01T00:00:00.000Z"


def old_store(tmp_path):
    path = tmp_path / "old.db"
    with closing(connect(path)) as conn:
        create_baseline(conn)
        conn.execute(
            "INSERT INTO page (id, slug, title, created_at, updated_at)"
            " VALUES ('P', 'p', 'P', ?, ?)",
            (T, T),
        )
        conn.execute(
            "INSERT INTO capture (id, kind, source, author, created_at, received_at,"
            " page_id) VALUES ('C', 'photo', 'pwa', 'me', ?, ?, 'P')",
            (T, T),
        )
        for n in (1, 2, 3):  # the triggers supersede the last each time
            conn.execute(
                "INSERT INTO writeup (page_id, version, producer, prompt_version,"
                " summary, text, guidance, created_at) VALUES ('P', ?, 'm', 'v', ?,"
                " ?, ?, ?)",
                (n, f"s{n}", f"text {n}", f"g{n}", f"{T[:-2]}{n}Z"),
            )
        for kind, texts in (("ocr", ("old words", "new words")),
                            ("excalidraw", (None, None, None))):  # fmt: skip
            for n, text in enumerate(texts, 1):
                conn.execute(
                    "INSERT INTO derived (capture_id, source_sha256, kind, version,"
                    " producer, text, data, created_at) VALUES ('C', 's', ?, ?, 'm',"
                    " ?, ?, ?)",
                    (kind, n, text, None if text else '{"elements": []}', T),
                )
        conn.commit()
    return path


def test_migrating_keeps_the_current_writeup_and_readings_and_all_drawings(tmp_path):
    path = old_store(tmp_path)
    with closing(connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM writeup").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM chunk").fetchone()[0] == 1
    migrate(path)
    with closing(connect(path)) as conn:
        rows = conn.execute("SELECT * FROM writeup").fetchall()
        assert len(rows) == 1
        assert (rows[0]["text"], rows[0]["guidance"]) == ("text 3", "g3")
        assert {"version", "superseded_at", "restored_from", "id"}.isdisjoint(
            rows[0].keys()
        )
        ocr = conn.execute("SELECT version, text FROM derived WHERE kind = 'ocr'")
        assert [tuple(r) for r in ocr] == [(2, "new words")]
        draw = conn.execute(
            "SELECT version FROM derived WHERE kind = 'excalidraw' ORDER BY version"
        )
        assert [r[0] for r in draw] == [1, 2, 3]  # a drawing keeps its history
        found = conn.execute("SELECT text FROM chunk WHERE derived_id IS NOT NULL")
        assert [r[0] for r in found] == ["new words"]
        hits = conn.execute(
            "SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'words'"
        ).fetchall()
        assert len(hits) == 1
        conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('integrity-check')")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # one row a page from now on: a second insert is refused
        stmt = (
            "INSERT INTO writeup (page_id, producer, prompt_version, text, created_at)"
            " VALUES ('P', 'm', 'v', 'x', ?)"
        )
        try:
            conn.execute(stmt, (T,))
        except Exception as err:  # noqa: BLE001
            assert "UNIQUE" in str(err)
        else:
            raise AssertionError("two write-ups for one page")
