"""Smoke tests for Sheng REST (create table → full autoplay HTTP until scored)."""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import sheng_rest_autoplay_until_scored, sheng_rest_finish_progressive_deal


client = TestClient(app)


def test_sheng_rest_autoplay_four_players() -> None:
    r = client.post("/api/sheng/tables", json={"num_players": 4, "seed": 4242, "declarer_seat": 0})
    assert r.status_code == 200, r.text
    data = r.json()
    table_id = data["table_id"]
    tokens = data["tokens"]

    sheng_rest_autoplay_until_scored(client, table_id, tokens)


def test_view_card_objects_include_graphical_fields() -> None:
    r = client.post("/api/sheng/tables", json={"num_players": 4, "seed": 42})
    assert r.status_code == 200, r.text
    data = r.json()
    tid = data["table_id"]
    toks = data["tokens"]
    sheng_rest_finish_progressive_deal(client, tid, toks["0"])
    st = client.get("/api/sheng/tables/" + tid, params={"token": toks["0"]}).json()
    assert st["phase"] == "declare"
    assert st.get("declare_to_act_seat") is not None
    c0 = st["hands"][0][0]
    assert c0.get("kind") == "regular"
    assert c0.get("suit") in ("C", "D", "H", "S")
    assert isinstance(c0.get("rank"), int)
    assert "label" in c0
