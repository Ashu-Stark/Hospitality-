"""GET /interventions: stored closed-loop interventions with their linked task's status
(open vs completed is derived from the task). All data is SYNTHETIC."""

from datetime import datetime, timedelta


class FixedClock:
    def __init__(self, now) -> None:  # noqa: ANN001
        self._now = now

    def now(self):  # noqa: ANN201
        return self._now


def test_interventions_follow_their_tasks(client) -> None:
    assert client.get("/interventions").json() == []
    loop = client.post("/loop/run").json()
    rows = client.get("/interventions").json()
    assert len(rows) == len(loop["interventions"]) > 0
    assert [r["task_id"] for r in rows] == [i["task_id"] for i in loop["interventions"]]
    assert {r["task_status"] for r in rows} == {"open"}
    assert all(r["synthetic"] and r["week_start"] == loop["week_start"] for r in rows)
    # no personal attributes: employees are ids only
    assert not {"name", "gender", "age"} & set(rows[0])

    first, second = rows[0], rows[1]
    assert client.post(f"/tasks/{first['task_id']}/done").status_code == 200
    assert client.post(f"/tasks/{second['task_id']}/ack").status_code == 200
    by_id = {r["id"]: r for r in client.get("/interventions").json()}
    assert by_id[first["id"]]["task_status"] == "done"
    assert by_id[first["id"]]["task_done_at"] is not None
    assert by_id[second["id"]]["task_status"] == "acked"

    done = client.get("/interventions", params={"status": "done"}).json()
    open_ = client.get("/interventions", params={"status": "open"}).json()
    assert [r["id"] for r in done] == [first["id"]]
    assert len(open_) == len(rows) - 1 and first["id"] not in {r["id"] for r in open_}

    emp = first["employee_id"]
    mine = client.get("/interventions", params={"employee_id": emp}).json()
    assert mine and all(r["employee_id"] == emp for r in mine)
    week = client.get("/interventions", params={"week_start": loop["week_start"]}).json()
    assert len(week) == len(rows)
    assert client.get("/interventions", params={"week_start": "2000-01-03"}).json() == []
    assert client.get("/interventions", params={"status": "bogus"}).status_code == 422

    # past every deadline: tasks not done become overdue; the done one stays done
    late = max(r["task_deadline"] for r in rows)
    client.app.state.clock = FixedClock(datetime.fromisoformat(late) + timedelta(days=1))
    statuses = {r["id"]: r["task_status"] for r in client.get("/interventions").json()}
    assert statuses[first["id"]] == "done"
    assert all(s == "overdue" for i, s in statuses.items() if i != first["id"])
    assert len(client.get("/interventions", params={"status": "open"}).json()) == len(rows) - 1
