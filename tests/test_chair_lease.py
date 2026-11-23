"""The Chair runs only on the host that holds the cloud's lease (autonomous-tasks R3.1, R3.2). No model, no network."""
import pytest

from coven import board, council, host


class Cloud:
    """The cloud's lease: one holder, 120 s, decided by the first request."""
    def __init__(self):
        self.now, self.holder, self.until, self.asked = 0.0, None, 0.0, []

    def lease(self, who, action):
        self.asked.append((who, action))
        free = self.holder is None or self.until <= self.now
        if action == "release":
            if self.holder == who:
                self.holder = None
            return {"held": False, "holder": self.holder, "until": None}
        if self.holder == who or free:
            self.holder, self.until = who, self.now + 120
            return {"held": True, "holder": who, "until": self.until}
        return {"held": False, "holder": self.holder, "until": self.until}


def make_host(cloud, name, agents, monkeypatch, tmp_path):
    h = host.Host.__new__(host.Host)
    h.root, h.installed, h.chair_held, h._chair_at = tmp_path, agents, False, None
    h.clock = lambda: cloud.now
    h.name = name
    return h


@pytest.fixture()
def cloud(monkeypatch):
    c = Cloud()
    monkeypatch.setattr(board, "chair_lease", lambda root, action="claim": c.lease(str(root), action))
    return c


def hosts(cloud, monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    return (make_host(cloud, "a", ["grey-witch", "green-witch"], monkeypatch, a),
            make_host(cloud, "b", ["grey-witch", "green-witch"], monkeypatch, b))


def test_only_the_holder_runs_the_chair_and_the_others_keep_running(cloud, monkeypatch, tmp_path):
    a, b = hosts(cloud, monkeypatch, tmp_path)
    a._chair_refresh()
    b._chair_refresh()
    assert a.can_run == ["grey-witch", "green-witch"]
    assert b.can_run == ["green-witch"]


def test_the_other_takes_over_after_the_lease_lapses(cloud, monkeypatch, tmp_path):
    a, b = hosts(cloud, monkeypatch, tmp_path)
    a._chair_refresh()
    cloud.now = 130  # a stopped renewing
    b._chair_refresh()
    assert "grey-witch" in b.can_run


def test_renewal_every_40_seconds_and_a_failed_renewal_stops_the_role_at_once(cloud, monkeypatch, tmp_path):
    a, b = hosts(cloud, monkeypatch, tmp_path)
    a._chair_refresh()
    cloud.now = 20
    a._chair_refresh()
    assert [x[1] for x in cloud.asked] == ["claim"]  # too soon to ask again
    cloud.now = 45
    a._chair_refresh()
    assert cloud.asked[-1][1] == "renew" and a.chair_held
    cloud.holder = "someone else"
    cloud.now = 90
    a._chair_refresh()
    assert not a.chair_held and "grey-witch" not in a.can_run


def test_an_unreachable_cloud_stops_the_role(monkeypatch, tmp_path):
    def down(root, action="claim"):
        raise board.BoardError("cloud unreachable")
    monkeypatch.setattr(board, "chair_lease", down)
    h = make_host(None, "a", ["grey-witch"], monkeypatch, tmp_path)
    h.clock = lambda: 0.0
    h.chair_held = True
    h._chair_refresh()
    assert h.can_run == []


def test_a_clean_stop_releases_and_the_other_claims_at_once(cloud, monkeypatch, tmp_path):
    a, b = hosts(cloud, monkeypatch, tmp_path)
    a._chair_refresh()
    a._chair_release()
    assert not a.chair_held
    b._chair_refresh()
    assert b.chair_held


def test_a_host_without_the_grey_witch_never_asks(cloud, monkeypatch, tmp_path):
    h = make_host(cloud, "a", ["green-witch"], monkeypatch, tmp_path)
    h._chair_refresh(force=True)
    h._chair_release()
    assert cloud.asked == [] and h.can_run == ["green-witch"]


def test_the_listener_steps_aside_for_the_host_that_advertises_the_chair(cloud, monkeypatch, tmp_path):
    a, b = hosts(cloud, monkeypatch, tmp_path)
    a._chair_refresh()
    b._chair_refresh()
    chat = {"hosts": [{"online": True, "agents": b.can_run}]}
    assert not council.chair_on_a_host(chat)  # the one without the lease does not count
    chat = {"hosts": [{"online": True, "agents": a.can_run}, {"online": True, "agents": b.can_run}]}
    assert council.chair_on_a_host(chat)
