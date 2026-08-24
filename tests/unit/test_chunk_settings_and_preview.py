"""KB-1/KB-2 — how a document is cut was three module constants and one magic number.

`CHUNK_CHARS`, `OVERLAP_CHARS`, and — inside a list comprehension, with no name at all —
a floor of 50 characters below which a chunk was DISCARDED. A document of short paragraphs
lost content silently and still reported a chunk count for whatever survived.

Settings alone would be half a feature: the only way to see what a setting does was to
upload, read a number, delete, and try again, with an embedding call per attempt against a
local model. So preview ships with them, and embeds nothing.

The property doing the most work here is the dullest: **the defaults reproduce the previous
behaviour exactly.** The corpus was indexed under those constants, and a default that moved
would make old documents and new ones incomparable without either being re-indexed.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.knowledge.documents import (CHUNK_CHARS, MIN_CHUNK_CHARS, OVERLAP_CHARS,
                                        ChunkSettings, ChunkSettingsError,
                                        _split_into_chunks)

client = TestClient(app)

PARA_A = "Alpha paragraph, long enough to survive the minimum chunk length threshold. " * 3
PARA_B = "Beta paragraph, also comfortably above the minimum chunk length filter here. " * 3
BODY = f"{PARA_A}\n\n{PARA_B}"


def _preview(body: str = BODY, settings: dict | None = None, name: str = "doc.txt"):
    data = {"chunk_settings": json.dumps(settings)} if settings else {}
    return client.post("/documents/preview",
                       files={"file": (name, io.BytesIO(body.encode()), "text/plain")},
                       data=data)


# ── the defaults are the old constants ───────────────────────────────────────────

def test_the_constants_became_defaults_and_did_not_move():
    """If this fails, every document already in the corpus was cut differently from every
    document indexed after the change, and nothing anywhere would say so."""
    s = ChunkSettings()

    assert (s.max_chars, s.overlap_chars, s.min_chars) == (CHUNK_CHARS, OVERLAP_CHARS,
                                                           MIN_CHUNK_CHARS)
    assert s.delimiter == "\n\n" and s.collapse_whitespace is True
    assert s.strip_urls_emails is False, "deleting URLs must be opt-in, not assumed"


def test_no_settings_produces_what_the_old_chunker_produced():
    assert _split_into_chunks(BODY) == _split_into_chunks(BODY, ChunkSettings())


def test_a_document_with_no_recorded_settings_reads_as_the_defaults():
    """Every document indexed before KB-1 has no `chunk_settings` key, and the defaults ARE
    what cut them — so absence must mean defaults, not an error."""
    assert ChunkSettings.from_dict(None) == ChunkSettings()
    assert ChunkSettings.from_dict({}) == ChunkSettings()
    assert ChunkSettings.from_dict({"unknown_key": 1}) == ChunkSettings()


# ── the magic number, now visible ────────────────────────────────────────────────

def test_short_chunks_were_being_discarded_and_now_that_is_a_setting():
    """The one that was never a knob. `min_chars` lived inside a list comprehension, so a
    document of short paragraphs lost content with no record anywhere."""
    tiny = "Too short."

    assert _split_into_chunks(tiny) == []
    assert _split_into_chunks(tiny, ChunkSettings(min_chars=0)) == [tiny]


# ── settings that cannot work are refused where they can be explained ────────────

def test_an_overlap_at_or_above_the_size_is_refused():
    """Not merely wrong: the hard-split path steps by (max - overlap), so this is a zero or
    negative step — a ValueError from range(), or a silently empty result."""
    with pytest.raises(ChunkSettingsError, match="smaller than max_chars"):
        ChunkSettings(max_chars=100, overlap_chars=100)
    with pytest.raises(ChunkSettingsError):
        ChunkSettings(max_chars=100, overlap_chars=500)


def test_an_empty_delimiter_is_refused():
    with pytest.raises(ChunkSettingsError, match="delimiter"):
        ChunkSettings(delimiter="")


@pytest.mark.parametrize("bad", [{"max_chars": 0}, {"overlap_chars": -1}, {"min_chars": -5}])
def test_nonsense_numbers_are_refused(bad):
    with pytest.raises(ChunkSettingsError):
        ChunkSettings(**bad)


# ── the settings actually change the cut ─────────────────────────────────────────

def test_a_smaller_size_produces_more_chunks():
    default = _split_into_chunks(BODY)
    small = _split_into_chunks(BODY, ChunkSettings(max_chars=200, overlap_chars=20))

    assert len(small) > len(default)
    assert all(len(c) <= 200 for c in small)


def test_the_delimiter_decides_where_a_split_may_happen():
    """Not how many chunks come out — the chunker PACKS pieces up to `max_chars`, so three
    short paragraphs still become one chunk. What the delimiter decides is whether the text
    has any boundaries at all. Under the default `\n\n` this text is one indivisible
    paragraph; under `---` it is three pieces the packer may separate."""
    text = "one---two---three"
    tight = dict(min_chars=0, max_chars=5, overlap_chars=0)

    # Wrong delimiter: no boundary exists, so the text is HARD-SPLIT mid-word — which is
    # the failure the setting exists to prevent, and it is silent.
    assert _split_into_chunks(text, ChunkSettings(**tight)) == \
        ["one--", "-two-", "--thr", "ee"]
    # Right delimiter: it splits where the meaning does.
    assert _split_into_chunks(text, ChunkSettings(delimiter="---", **tight)) == \
        ["one", "two", "three"]


def test_stripping_urls_is_available_and_off_by_default():
    """Offered, not assumed: a policy that cites a source loses the citation."""
    text = "See https://example.com/policy or mail us at ops@example.com for details. " * 3

    kept = _split_into_chunks(text, ChunkSettings(min_chars=0))[0]
    stripped = _split_into_chunks(text, ChunkSettings(min_chars=0,
                                                      strip_urls_emails=True))[0]

    assert "https://example.com/policy" in kept and "ops@example.com" in kept
    assert "https://" not in stripped and "@example.com" not in stripped


# ── preview: KB-2 ────────────────────────────────────────────────────────────────

def test_preview_returns_chunks_without_indexing_anything():
    """The whole point. Safe to call repeatedly, because it writes nothing."""
    before = len(client.get("/documents").json())

    body = _preview().json()

    assert body["total_chunks"] >= 1
    assert body["chunks"][0]["text"]
    assert len(client.get("/documents").json()) == before


def test_preview_echoes_the_settings_that_produced_it():
    """A preview whose settings are implicit cannot be compared with the next one."""
    body = _preview(settings={"max_chars": 200, "overlap_chars": 20}).json()

    assert body["settings"]["max_chars"] == 200
    assert body["settings"]["overlap_chars"] == 20
    assert all(c["characters"] <= 200 for c in body["chunks"])


def test_preview_refuses_impossible_settings_with_the_reason():
    r = _preview(settings={"max_chars": 100, "overlap_chars": 100})

    assert r.status_code == 422 and "smaller than max_chars" in r.json()["detail"]


def test_preview_refuses_the_same_file_types_upload_does():
    """A preview that accepted what upload rejects shows a person chunks they can never
    index."""
    r = _preview(name="notes.pptx")

    assert r.status_code == 422 and "Unsupported file type" in r.json()["detail"]


def test_preview_is_bounded():
    """It runs on every adjustment; returning a whole book would defeat the purpose."""
    many = "\n\n".join(f"Paragraph {i} with enough text to clear the minimum length filter."
                       for i in range(200))

    body = _preview(many, settings={"max_chars": 100, "overlap_chars": 10}).json()

    assert body["total_chunks"] > body["shown"]
    assert body["shown"] <= 10


def test_the_token_count_is_named_as_an_estimate():
    """A real count needs the embedder's tokeniser, which this endpoint exists to avoid
    calling. Reporting a guess as `tokens` would be a small lie on every preview."""
    chunk = _preview().json()["chunks"][0]

    assert "tokens_estimate" in chunk and "tokens" not in chunk


# ── the settings are recorded, so a re-index is reproducible ─────────────────────

def test_indexing_records_the_settings_it_used(monkeypatch, tmp_path):
    """Without this a re-index is a guess: the defaults may have moved, or a person may
    have chosen settings once and be unable to recall them."""
    from aughor.knowledge import indexer

    recorded = {}
    monkeypatch.setattr(indexer, "_ensure_collection", lambda: None)
    monkeypatch.setattr(indexer, "_upsert_chunks", lambda _c: None)
    monkeypatch.setattr(indexer, "_register",
                        lambda *a, **k: recorded.update(args=a, kwargs=k))

    doc = tmp_path / "d.txt"
    doc.write_text(BODY)
    indexer.index_file(doc, settings=ChunkSettings(max_chars=200, overlap_chars=20))

    assert recorded["kwargs"]["settings"]["max_chars"] == 200


def test_indexing_with_no_settings_records_none(monkeypatch, tmp_path):
    """Absence stays absence — writing the defaults in would claim a choice nobody made,
    and would freeze today's defaults into every document."""
    from aughor.knowledge import indexer

    recorded = {}
    monkeypatch.setattr(indexer, "_ensure_collection", lambda: None)
    monkeypatch.setattr(indexer, "_upsert_chunks", lambda _c: None)
    monkeypatch.setattr(indexer, "_register",
                        lambda *a, **k: recorded.update(kwargs=k))

    doc = tmp_path / "d.txt"
    doc.write_text(BODY)
    indexer.index_file(doc)

    assert recorded["kwargs"]["settings"] is None
