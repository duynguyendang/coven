"""A failed task says why: the host's own facts travel with the failed status (contract: task_status `failure`)."""

from __future__ import annotations

from coven import host
from tests.test_host import FakeCloud, Runner, builds_cart, does_nothing, git, repo, run_dev  # noqa: F401 - fixtures


def test_the_reason_is_classified():
    cases = {
        "nothing changed in the checkout": "no_change",
        "nothing changed in the checkout, and the task's verify command did not pass on the unchanged checkout": "no_change",
        "feature/x changes nothing against main": "no_change",
        "files outside the task's paths (src): a.py, b.py. Undo those changes": "outside_paths",
        "the task's verify command did not pass (fail: exit 1); see verify-x.log": "verify_failed",
        "no result within 1800 s": "timeout",
        "the run gave no answer": "no_answer",
        "kiro-cli is not installed on this host": "kiro_error",
        "Kiro Web did not push coven/x-1 to origin within 600 s": "cloud",
        "KeyError: 'x'": "error",
    }
    assert {text: host.failure_code(text) for text in cases} == cases


def test_a_build_that_changes_nothing_fails_with_the_facts_a_person_needs(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    runner = Runner({"green-witch": lambda cwd, prompt: ("I looked and it is already there.", None)})
    run_dev(repo, runner)
    (ref, failure), = cloud.failures
    assert ref == "shop#1"
    assert failure["cause"] == "no_change" and failure["attempts"] == 2 and failure["seconds"] >= 0
    assert failure["summary"] == "nothing changed in the checkout"
    assert failure["said"] == "I looked and it is already there."
    assert "mark the task done" in failure["next"] and "Retry" in failure["next"]
    assert host.load(repo)["shop#1"]["failure"]["cause"] == "no_change", "kept on the host too (coven host status)"


def test_a_change_to_the_tasks_paths_on_the_base_branch_is_pointed_out(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)

    def lands_on_main(cwd, prompt):  # the work reaches the base branch another way while the Dev works
        (repo / "src" / "cart").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "cart" / "total.py").write_text("x = 1\n")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--allow-empty", "-m", "landed elsewhere")
        return "nothing to do", None

    run_dev(repo, Runner({"green-witch": lands_on_main}))
    failure = cloud.failures[-1][1]
    assert failure["cause"] == "no_change" and failure["base_changed"] is True
    assert "already be there" in failure["next"]


def test_files_outside_the_paths_are_listed(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)

    def strays(cwd, prompt):
        (cwd / "elsewhere").mkdir(exist_ok=True)
        (cwd / "elsewhere" / "a.py").write_text("x\n")
        return "done", None

    run_dev(repo, Runner({"green-witch": strays}))
    failure = cloud.failures[-1][1]
    assert failure["cause"] == "outside_paths" and failure["outside_paths"] == ["elsewhere/a.py"]


def test_secrets_in_what_the_agent_said_are_redacted(repo, monkeypatch):
    cloud = FakeCloud().install(monkeypatch)
    run_dev(repo, Runner({"green-witch": lambda cwd, prompt: ("my key is AKIAIOSFODNN7EXAMPLE sorry", None)}))
    said = cloud.failures[-1][1]["said"]
    assert "AKIAIOSFODNN7EXAMPLE" not in said and "REDACTED" in said
