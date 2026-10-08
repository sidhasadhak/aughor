"""The cockpit as a canvas (docs/COCKPIT_CANVAS_2026-10-08.md): a note and an image on a person's
cockpit, their stamps the server's, a model that may arrange them and never make one, and an
image that is this connection's or is not shown.

The laws under test are §3 of the note. Each is asserted by a token of the sentence a person
reads, never by "refused" alone.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aughor.cockpit import cards, images, propose, validate as V, versions
from aughor.cockpit.home import Home
from aughor.dashboard.models import DashboardCard
from aughor.kernel.flags import flag_overrides

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "lib" / "cockpit" / "premise.fixture.json"

needs_rules = pytest.mark.skipif(
    shutil.which("node") is None or not V._BUNDLE.exists(),
    reason="the cockpit's rules need node + validate.bundle.mjs")

ME = "default"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def volumes(tmp_path, monkeypatch):
    """Volumes and their catalog in a temp home, as the files tests arrange them."""
    import aughor.files.store as vol_store
    import aughor.metastore.store as ms_store
    from aughor.control_plane import vending
    monkeypatch.setattr(ms_store, "_DB_PATH", tmp_path / "metastore.db")
    monkeypatch.setattr(vol_store, "_DB_PATH", tmp_path / "volumes.db")
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    return tmp_path


class Desk:
    def __init__(self):
        tag = uuid.uuid4().hex[:6]
        self.connection = f"conn{tag}"
        self.home = Home(self.connection, ME, f"returns-{tag}")
        self.rate, self.net = f"rate{tag}", f"net{tag}"
        for cid, title in ((self.rate, "Return rate"), (self.net, "Net revenue")):
            cards.place(self.home, DashboardCard(id=cid, kind="kpi", title=title, sql="SELECT 1"))
        text = FIXTURE.read_text().replace("c7f3a001", self.rate).replace("c91b2002", self.net)
        self.spec = json.loads(text)
        from aughor.metastore import upsert_catalog
        upsert_catalog(self.connection, name=self.connection, conn_id=self.connection)

    def with_note(self, text="Target for Q4: under **10%**.", key="note-1", **props):
        self.spec["elements"][key] = {"type": "Note", "props": {"text": text, **props}, "children": []}
        self.spec["elements"]["sec-headline"]["children"].append(key)
        return self

    def with_image(self, object_id, caption="Q4 promo calendar", key="image-1"):
        self.spec["elements"][key] = {"type": "Image", "props": {"object": object_id, "caption": caption}, "children": []}
        self.spec["elements"]["sec-headline"]["children"].append(key)
        return self

    def keep(self, spec=None, by="user:amit", **kw):
        return versions.keep(self.home, spec or self.spec, approved_by=by, source="a person's own hand",
                             written_by_model=False, **kw)


def said(kept) -> str:
    return " ".join(kept.sentences)


# ── a note's stamps are the server's ─────────────────────────────────────────────────────────

@needs_rules
def test_a_note_is_stamped_with_who_kept_it_and_when_whatever_the_client_sent(volumes):
    desk = Desk().with_note(author="user:someone-else", written_at="1999-01-01T00:00:00Z")
    kept = desk.keep(by="user:amit")
    assert kept.kept, said(kept)
    note = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]
    assert note["author"] == "user:amit"
    assert note["written_at"].startswith("20") and note["written_at"] != "1999-01-01T00:00:00Z"


@needs_rules
def test_a_note_moved_keeps_its_stamps_and_one_rewritten_is_stamped_again(volumes):
    desk = Desk().with_note()
    assert desk.keep(by="user:amit").kept
    first = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]

    # Moved by another hand: the words are the same, so the stamp stays amit's.
    moved = json.loads(json.dumps(versions.latest(desk.home)["spec"]))
    moved["elements"]["note-1"]["props"]["size"] = "wide"
    kept = desk.keep(moved, by="user:priya")
    assert kept.kept, said(kept)
    again = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]
    assert (again["author"], again["written_at"]) == (first["author"], first["written_at"])

    # Rewritten: the stamp is the rewriter's.
    rewritten = json.loads(json.dumps(versions.latest(desk.home)["spec"]))
    rewritten["elements"]["note-1"]["props"]["text"] = "Target for Q4: under 9%."
    assert desk.keep(rewritten, by="user:priya").kept
    third = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]
    assert third["author"] == "user:priya" and third["written_at"] >= first["written_at"]


@needs_rules
def test_a_note_may_hold_a_figure_because_the_words_are_the_persons(volumes):
    """The numerals law is for text a model wrote. A note is a person's, under either reading."""
    desk = Desk().with_note(text="Under 10% by Q4, or $1.2M is at risk.")
    kept = versions.keep(desk.home, desk.spec, approved_by="user:amit", source="proposal p1", written_by_model=True)
    assert kept.kept, said(kept)


@needs_rules
def test_going_back_carries_the_stamps_the_server_wrote(volumes):
    desk = Desk().with_note()
    assert desk.keep(by="user:amit").kept
    v1 = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]
    without = json.loads(json.dumps(versions.latest(desk.home)["spec"]))
    del without["elements"]["note-1"]
    without["elements"]["sec-headline"]["children"].remove("note-1")
    assert desk.keep(without, by="user:priya").kept
    back = versions.restore(desk.home, 1, approved_by="user:priya")
    assert back.kept, said(back)
    restored = versions.latest(desk.home)["spec"]["elements"]["note-1"]["props"]
    assert (restored["author"], restored["written_at"]) == (v1["author"], v1["written_at"])


# ── an image is this connection's, or it is not shown ────────────────────────────────────────

def test_the_bytes_say_what_an_image_is_and_an_svg_with_script_is_refused():
    assert images.sniffed(PNG) == ("image/png", "")
    assert images.sniffed(b"\xff\xd8\xff\xe0" + b"\x00" * 8)[0] == "image/jpeg"
    assert images.sniffed(b"GIF89a" + b"\x00" * 8)[0] == "image/gif"
    assert images.sniffed(b"RIFF\x00\x00\x00\x00WEBPVP8 ")[0] == "image/webp"
    assert images.sniffed(b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')[0] == "image/svg+xml"
    kind, why = images.sniffed(b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect/></svg>')
    assert kind == "" and "script" in why
    kind, why = images.sniffed(b"<svg><script>alert(1)</script></svg>")
    assert kind == "" and "script" in why
    kind, why = images.sniffed(b"%PDF-1.4 ...")
    assert kind == "" and "not a PNG, JPEG, GIF, WebP or SVG image" in why
    assert images.sniffed(b"")[1] == "The file is empty."


def test_an_image_is_kept_with_its_uploader_and_refused_over_the_cap(volumes):
    desk = Desk()
    stamp = images.put_image(desk.connection, "promo.png", PNG, "image/png", uploaded_by="user:amit")
    assert stamp["uploaded_by"] == "user:amit" and stamp["file_name"] == "promo.png" and stamp["content_type"] == "image/png"
    assert images.stamp_of(desk.connection, stamp["object"])["readable"] is True
    data, kind = images.read_image(desk.connection, stamp["object"])
    assert data == PNG and kind == "image/png"
    with pytest.raises(images.Refused, match="the cap is 5 MB"):
        images.put_image(desk.connection, "big.png", PNG + b"\x00" * images.MAX_BYTES, uploaded_by="user:amit")
    with pytest.raises(images.Refused, match="sent as text/html"):
        images.put_image(desk.connection, "page.html", b"<html><body>hi</body></html>", "text/html", uploaded_by="user:amit")
    with pytest.raises(images.Refused, match="uploaded it"):
        images.put_image(desk.connection, "promo.png", PNG, uploaded_by="")


def test_another_connections_image_is_not_this_cockpits(volumes):
    mine, theirs = Desk(), Desk()
    stamp = images.put_image(theirs.connection, "promo.png", PNG, uploaded_by="user:priya")
    assert images.stamp_of(mine.connection, stamp["object"]) is None
    stamps = images.stamps_for(mine.connection, mine.with_image(stamp["object"]).spec)
    assert stamps[stamp["object"]]["readable"] is False and "not in this connection" in stamps[stamp["object"]]["why"]
    with pytest.raises(images.Refused):
        images.read_image(mine.connection, stamp["object"])


@needs_rules
def test_a_cockpit_places_only_an_image_of_its_own_connection(volumes):
    desk = Desk()
    mine = images.put_image(desk.connection, "promo.png", PNG, uploaded_by="user:amit")["object"]
    kept = desk.with_image(mine).keep()
    assert kept.kept, said(kept)
    other = Desk()
    theirs = images.put_image(other.connection, "promo.png", PNG, uploaded_by="user:priya")["object"]
    refused = Desk().with_image(theirs).keep()
    assert refused.status == versions.REFUSED
    assert "not an image uploaded to this connection's cockpits" in said(refused)


# ── a model arranges a note or an image and never makes one ──────────────────────────────────

def _premise_with_statics():
    return {"elements": {
        "note-1": {"type": "Note", "props": {"text": "Check ops before the 15th."}, "children": []},
        "image-1": {"type": "Image", "props": {"object": "ab12cd34ef56", "caption": "Promo calendar"}, "children": []},
    }}


def test_a_new_cockpit_from_a_model_holds_no_note_and_no_image():
    said_ = propose.statics_written(None, _premise_with_statics(), propose.MODE_NEW)
    assert len(said_) == 2
    assert all("A new cockpit holds no note and no image" in s for s in said_)


def test_an_edit_may_move_or_resize_a_note_and_may_not_add_one_or_write_it():
    before = _premise_with_statics()
    moved = json.loads(json.dumps(before))
    moved["elements"]["note-1"]["props"]["size"] = "wide"
    assert propose.statics_written(before, moved, propose.MODE_EDIT) == []

    added = json.loads(json.dumps(before))
    added["elements"]["note-2"] = {"type": "Note", "props": {"text": "Written by a model."}, "children": []}
    assert "never add one" in " ".join(propose.statics_written(before, added, propose.MODE_EDIT))

    rewritten = json.loads(json.dumps(before))
    rewritten["elements"]["note-1"]["props"]["text"] = "The model's words."
    assert "never write it" in " ".join(propose.statics_written(before, rewritten, propose.MODE_EDIT))

    swapped = json.loads(json.dumps(before))
    swapped["elements"]["image-1"]["props"]["object"] = "ffffffffffff"
    assert "never choose one" in " ".join(propose.statics_written(before, swapped, propose.MODE_EDIT))

    gone = {"elements": {}}
    assert propose.statics_written(before, gone, propose.MODE_EDIT) == []


def test_the_outline_names_a_note_and_an_image_as_a_person_reads_them():
    spec = {"root": "cockpit", "elements": {
        "cockpit": {"type": "Cockpit", "props": {"title": "Returns"}, "children": ["sec"]},
        "sec": {"type": "Section", "props": {"title": "Working view"}, "children": ["card-1", "note-1", "image-1"]},
        "card-1": {"type": "Card", "props": {"card": "c1", "size": "wide"}, "children": []},
        **_premise_with_statics()["elements"],
    }}
    lines = propose.outline(spec, {"c1": "Return rate"}, set())[0]["sections"][0]["cards"]
    assert [l["title"] for l in lines] == ["Return rate", "Note · Check ops before the 15th.", "Image · Promo calendar"]
    assert [l["size"] for l in lines] == ["wide", "small", "small"]
    assert lines[1]["static"] == "note" and lines[2]["static"] == "image"
    off = propose.taken_off(spec, ["note-1", "image-1"], {})
    assert [o["what"] for o in off] == ["note", "image"] and off[0]["from"] == "Working view"


# ── over HTTP ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture
def on():
    with flag_overrides({"cockpit.composed": True}):
        yield


@needs_rules
def test_an_image_is_uploaded_placed_read_back_and_stamped(client, on, volumes):
    desk = Desk()
    q = {"connection_id": desk.connection}
    up = client.post("/cockpits/images", params=q, files={"file": ("promo.png", PNG, "image/png")})
    assert up.status_code == 200, up.text
    stamp = up.json()
    assert stamp["readable"] and stamp["file_name"] == "promo.png" and stamp["uploaded_by"].startswith("user:")

    kept = client.put(f"/cockpits/{desk.home.cockpit_id}", params=q, json={"spec": desk.with_image(stamp["object"]).spec})
    assert kept.status_code == 200, kept.text
    read = client.get(f"/cockpits/{desk.home.cockpit_id}", params=q).json()
    assert read["images"][stamp["object"]]["uploaded_by"] == stamp["uploaded_by"]

    bytes_ = client.get(f"/cockpits/images/{stamp['object']}", params=q)
    assert bytes_.status_code == 200 and bytes_.content == PNG
    assert bytes_.headers["content-type"].startswith("image/png")
    assert bytes_.headers["x-content-type-options"] == "nosniff"

    refused = client.post("/cockpits/images", params=q, files={"file": ("page.html", b"<html>hi</html>", "text/html")})
    assert refused.status_code == 422 and "not a PNG" in refused.json()["detail"]
    gone = client.get("/cockpits/images/nope", params=q)
    assert gone.status_code == 404


def test_off_the_image_routes_answer_404(client, volumes):
    desk = Desk()
    q = {"connection_id": desk.connection}
    assert client.post("/cockpits/images", params=q, files={"file": ("p.png", PNG, "image/png")}).status_code == 404
    assert client.get("/cockpits/images/abc", params=q).status_code == 404
