import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def sheng_rest_finish_progressive_deal(
    client: TestClient,
    table_id: str,
    token: str,
    *,
    max_iters: int = 200,
) -> None:
    """Advance dealt cards until the full hand is visible (declare phase only)."""

    for _ in range(max_iters):
        st = client.get(f"/api/sheng/tables/{table_id}", params={"token": token}).json()
        if st.get("phase") != "declare":
            return
        cur = int(st.get("deal_reveal_steps") or 0)
        tot = int(st.get("deal_total_steps") or 0)
        if cur >= tot:
            return
        steps = min(20, tot - cur)
        r = client.post(
            f"/api/sheng/tables/{table_id}/deal_advance",
            json={"token": token, "steps": steps},
        )
        assert r.status_code == 200, r.text


def sheng_rest_bury_kitty(client: TestClient, table_id: str, tokens: dict[str, str]) -> None:
    st0 = client.get(f"/api/sheng/tables/{table_id}", params={"token": tokens["0"]}).json()
    assert st0.get("phase") == "kitty", st0
    dseat = str(int(st0["declarer_seat"]))
    st = client.get(f"/api/sheng/tables/{table_id}", params={"token": tokens[dseat]}).json()
    bury_n = int(st.get("kitty", {}).get("bury_needed") or 0)
    assert bury_n > 0
    mine = st["hands"][int(dseat)]
    ids = sorted(c["cid"] for c in mine)[:bury_n]
    resp = client.post(
        f"/api/sheng/tables/{table_id}/bury",
        json={"token": tokens[dseat], "card_ids": ids},
    )
    assert resp.status_code == 200, resp.text


def sheng_rest_autoplay_until_scored(client: TestClient, table_id: str, tokens: dict[str, str]) -> None:
    safety = 0
    max_plays = 900
    while safety < max_plays:
        sheng_rest_finish_progressive_deal(client, table_id, tokens["0"])
        st_pub = client.get(f"/api/sheng/tables/{table_id}", params={"token": tokens["0"]}).json()
        if st_pub["phase"] == "scored":
            return
        if st_pub["phase"] == "declare":
            n = int(st_pub["num_players"])
            posted = False
            for si in range(n):
                tok = tokens[str(si)]
                st_i = client.get(f"/api/sheng/tables/{table_id}", params={"token": tok}).json()
                ld = st_i.get("legal_declare") or []
                if not ld:
                    continue
                resp = client.post(
                    f"/api/sheng/tables/{table_id}/declare",
                    json={"token": tok, "action": "pass"},
                )
                assert resp.status_code == 200, resp.text
                posted = True
                break
            assert posted, "no seat had a legal declare action"
            safety += 1
            continue
        if st_pub["phase"] == "kitty":
            sheng_rest_bury_kitty(client, table_id, tokens)
            safety += 1
            continue
        actor_seat = str(int(st_pub["to_act_seat"]))  # type: ignore[arg-type]
        st = client.get(
            f"/api/sheng/tables/{table_id}",
            params={"token": tokens[actor_seat]},
        ).json()
        ids: list[Any] = list(st["legal_plays"][0]["card_ids"])  # type: ignore[index]
        resp = client.post(
            f"/api/sheng/tables/{table_id}/actions",
            json={"token": tokens[actor_seat], "card_ids": ids},
        )
        assert resp.status_code == 200, resp.text
        safety += 1
    raise AssertionError("hand timed out")
