"""Smoke tests for Sheng REST (create table → full autoplay HTTP until scored)."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_sheng_rest_autoplay_four_players() -> None:
    r = client.post("/api/sheng/tables", json={"num_players": 4, "seed": 4242, "declarer_seat": 0})
    assert r.status_code == 200, r.text
    data = r.json()
    table_id = data["table_id"]
    tokens = data["tokens"]

    safety = 0
    max_plays = 300
    while safety < max_plays:
        st_pub = client.get("/api/sheng/tables/" + table_id, params={"token": tokens["0"]}).json()
        if st_pub["phase"] == "scored":
            assert st_pub["hand_summary"] is not None
            return
        actor_seat = int(st_pub["to_act_seat"])  # type: ignore[arg-type]
        st = client.get(
            "/api/sheng/tables/" + table_id,
            params={"token": tokens[str(actor_seat)]},
        ).json()
        ids = st["legal_plays"][0]["card_ids"]  # type: ignore[index]
        resp = client.post(
            "/api/sheng/tables/" + table_id + "/actions",
            json={"token": tokens[str(actor_seat)], "card_ids": ids},
        )
        assert resp.status_code == 200, resp.text
        safety += 1

    raise AssertionError("hand did not finish")


def test_view_card_objects_include_graphical_fields() -> None:
    r = client.post("/api/sheng/tables", json={"num_players": 4, "seed": 42})
    assert r.status_code == 200, r.text
    st = r.json()["state_seat_0"]
    c0 = st["hands"][0][0]
    assert c0.get("kind") == "regular"
    assert c0.get("suit") in ("C", "D", "H", "S")
    assert isinstance(c0.get("rank"), int)
    assert "label" in c0
