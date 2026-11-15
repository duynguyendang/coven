"""run-host.sh runs its interpreter from COVEN_PY (a fake python and a fake kiro-cli record argv)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(tmp_path, coven_py):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "argv.log"
    (bin_dir / "kiro-cli").write_text("#!/bin/sh\nexit 0\n")
    fake = bin_dir / "fakepy"
    fake.write_text(
        '#!/bin/sh\n'
        'printf "%s\\n" "$*" >> "$FAKE_LOG"\n'
        'case "$*" in *" doctor"*) echo "health: 200";; *" member"*) echo "a@b:c";; esac\n'
        'exit 0\n'
    )
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        FAKE_LOG=str(log),
        COVEN_ROOT=str(tmp_path),
        COVEN_PY=coven_py.format(fake=fake),
    )
    r = subprocess.run(
        ["bash", str(ROOT / "run-host.sh"), "--agents", "elf", "--once"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    lines = log.read_text().splitlines() if log.exists() else []
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
