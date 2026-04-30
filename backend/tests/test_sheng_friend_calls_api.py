"""Friend-call declarations over REST / tables validation."""

from fastapi.testclient import TestClient

from app.main import app
from app.sheng.friend import FriendCall
from app.sheng.cards import Suit
from app.sheng.tables import validate_friend_calls


client = TestClient(app)


def test_validate_friend_calls_rules() -> None:
    validate_friend_calls(6, ())
    validate_friend_calls(6, (FriendCall(1, Suit.CLUBS, 14), FriendCall(2, Suit.CLUBS, 14)))

    try:
        validate_friend_calls(4, (FriendCall(1, Suit.CLUBS, 14),))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    try:
        validate_friend_calls(
            6,
            (FriendCall(1, Suit.CLUBS, 14),),
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_create_six_calls_and_view_lists_them() -> None:
    body = {
        "num_players": 6,
        "seed": 77,
        "declarer_seat": 2,
        "friend_calls": [
            {"nth": 1, "suit": "S", "rank": 14},
            {"nth": 2, "suit": "H", "rank": 13},
        ],
    }
    r = client.post("/api/sheng/tables", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    fc = data["state_seat_0"]["friend_calls"]
    assert len(fc) == 2
    assert fc[0]["nth"] == 1 and fc[0]["rank"] == 14
    assert data["state_seat_0"]["revealed_friend_seats"] == []
    assert data["state_seat_0"]["deal_epoch"] == 1
    assert "completed_tricks" in data["state_seat_0"]
    assert data["state_seat_0"]["completed_tricks"] == []


def test_create_four_with_friend_calls_400() -> None:
    r = client.post(
        "/api/sheng/tables",
        json={
            "num_players": 4,
            "friend_calls": [{"nth": 1, "suit": "C", "rank": 5}],
        },
    )
    assert r.status_code == 400

