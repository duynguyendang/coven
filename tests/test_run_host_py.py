"""run-host.sh runs its interpreter from COVEN_PY (a fake python and a fake kiro-cli record argv)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, coven_py, args=(), **extra_env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "argv.log"
    (bin_dir / "kiro-cli").write_text("#!/bin/sh\nexit 0\n")
    fake = bin_dir / "fakepy"
    fake.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$*" >> "$FAKE_LOG"\n'
        'case "$*" in *" doctor"*) echo "health: 200";; *" member"*) echo "a@b:c";; *"host run"*) echo "COVEN_AUTONOMOUS=$COVEN_AUTONOMOUS" >> "$FAKE_LOG.env";; esac\n'
        'exit 0\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "COVEN_AUTONOMOUS"}
    env.update(extra_env)
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        FAKE_LOG=str(log),
        COVEN_ROOT=str(tmp_path),
        COVEN_PY=coven_py.format(fake=fake),
    )
    r = subprocess.run(
        ["bash", str(ROOT / "run-host.sh"), "--agents", "elf", "--once", *args],
        env=env, capture_output=True, text=True, timeout=60,
    )
    lines = log.read_text().splitlines() if log.exists() else []
    seen = Path(f"{log}.env")
    r.env_seen = seen.read_text().splitlines() if seen.exists() else []  # the environment `coven host run` got
    return r, lines


def test_fake_python_is_used(tmp_path):
    r, lines = _run(tmp_path, "{fake}")
    assert r.returncode == 0, r.stderr
    assert lines and all("-m coven.cli" in ln for ln in lines)
    assert any("host run" in ln for ln in lines)


def test_py_with_spaces_and_quote_does_not_break(tmp_path):
    r, lines = _run(tmp_path, "{fake} -X it's")
    assert r.returncode == 0, r.stderr
    assert any(ln.startswith("-X it's -m coven.cli host run") for ln in lines)


def test_missing_interpreter_is_reported(tmp_path):
    r, _ = _run(tmp_path, "no-such-python-xyz")
    assert r.returncode == 1
    assert "no-such-python-xyz" in r.stderr


def test_logs_in_to_the_default_cloud_when_the_saved_login_points_elsewhere(tmp_path):
    r, lines = _run(tmp_path, "{fake}")
    assert r.returncode == 0, r.stderr
    logins = [ln for ln in lines if " login " in f" {ln} "]
    assert logins == ["-m coven.cli login --cloud-url https://52-220-6-189.sslip.io --token dev"]
    assert any(ln.endswith("relay down") for ln in lines), "the relay restarts on the new cloud"
    assert lines.index(logins[0]) < next(i for i, ln in enumerate(lines) if "host run" in ln)


def test_cloud_url_and_token_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("COVEN_CLOUD_URL", "https://cloud.example")
    monkeypatch.setenv("COVEN_TOKEN", "t0k")
    r, lines = _run(tmp_path, "{fake}")
    assert r.returncode == 0, r.stderr
    assert "-m coven.cli login --cloud-url https://cloud.example --token t0k" in lines


def test_the_local_runner_starts_autonomous_unless_told_otherwise(tmp_path):
    """run-host.sh sets COVEN_AUTONOMOUS=1 by default; `coven host run` itself stays opt-in (tests/test_cli.py)."""
    r, lines = _run(tmp_path, "{fake}")
    assert r.returncode == 0, r.stderr
    assert r.env_seen == ["COVEN_AUTONOMOUS=1"] and "autonomous mode on" in r.stdout
    assert "the Dev is not on this host" in r.stdout, "it says when nothing can be built"
    for args, env in (((), {"COVEN_AUTONOMOUS": "0"}), (("--manual",), {})):
        sub = tmp_path / f"run-{len(args)}"
        sub.mkdir()
        r, lines = _run(sub, "{fake}", args, **env)
        assert r.returncode == 0, r.stderr
        assert r.env_seen == ["COVEN_AUTONOMOUS=0"] and "autonomous mode on" not in r.stdout
        assert not any("--manual" in ln for ln in lines), "--manual is the script's own word, not passed on"
