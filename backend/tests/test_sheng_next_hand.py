"""Bank rotation + sequential hands (REST)."""

from fastapi.testclient import TestClient

from app.main import app
from app.sheng.tables import next_bank_declarer_seat


client = TestClient(app)


def _autoplay_until_scored(tab: str, toks: dict[str, str]) -> None:
    safety = 0
    max_plays = 400
    while safety < max_plays:
        st_pub = client.get("/api/sheng/tables/" + tab, params={"token": toks["0"]}).json()
        if st_pub["phase"] == "scored":
            return
        actor = int(st_pub["to_act_seat"])  # type: ignore[arg-type]
        st = client.get(
            "/api/sheng/tables/" + tab,
            params={"token": toks[str(actor)]},
        ).json()
        cid = int(st["legal_plays"][0]["cid"])  # type: ignore[index]
        resp = client.post(
            "/api/sheng/tables/" + tab + "/actions",
            json={"token": toks[str(actor)], "card_id": cid},
        )
        assert resp.status_code == 200, resp.text
        safety += 1
    raise AssertionError("hand timed out")


def test_next_bank_declarer_four_players_when_defenders_win() -> None:
    lb_attack = {"defenders_side_delta": 2}
    assert next_bank_declarer_seat(0, 4, lb_attack) == 1

    lb_keep = {"dealer_side_delta": 2, "defenders_side_delta": 0}
    assert next_bank_declarer_seat(0, 4, lb_keep) == 0

    lb_tie = {"tie_at_threshold": True, "swap_without_level": True}
    assert next_bank_declarer_seat(0, 4, lb_tie) == 1


def test_two_rest_hands_via_next_hand() -> None:
    res = client.post("/api/sheng/tables", json={"num_players": 4, "seed": 9001, "declarer_seat": 1})
    assert res.status_code == 200, res.text
    data = res.json()
    table_id = data["table_id"]
    tokens = data["tokens"]

    _autoplay_until_scored(table_id, tokens)

    r2 = client.post(
        "/api/sheng/tables/" + table_id + "/next_hand",
        json={"token": tokens["0"], "seed": 9002},
    )
    assert r2.status_code == 200, r2.text
    st = r2.json()["state"]
    assert st["phase"] == "play"
    assert st["leader"] == (int(st["declarer_seat"]) + 1) % int(st["num_players"])

    _autoplay_until_scored(table_id, tokens)


def test_next_hand_six_empty_friend_calls_stores_diagonal_mode() -> None:
    """Explicit friend_calls: [] on next_hand clears two-card friend mode for the new deal."""
    res = client.post(
        "/api/sheng/tables",
        json={
            "num_players": 6,
            "seed": 10101,
            "friend_calls": [
                {"nth": 1, "suit": "C", "rank": 9},
                {"nth": 1, "suit": "D", "rank": 8},
            ],
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    table_id = data["table_id"]
    tokens = data["tokens"]
    assert len(data["state_seat_0"]["friend_calls"]) == 2

    _autoplay_until_scored(table_id, tokens)

    r2 = client.post(
        "/api/sheng/tables/" + table_id + "/next_hand",
        json={"token": tokens["0"], "seed": 10102, "friend_calls": []},
    )
    assert r2.status_code == 200, r2.text
    st = r2.json()["state"]
    assert st["friend_calls"] == []
    assert st["revealed_friend_seats"] == []
