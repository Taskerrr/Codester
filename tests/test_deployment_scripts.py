"""Exercise real Bash/Git control flow without contacting servers or Docker."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codester.services import ServiceManager

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("bash") or not shutil.which("git"),
    reason="Remote deployment scripts target Linux Bash/Git",
)


def executable(path: Path, code: str) -> None:
    path.write_text(f"#!{sys.executable}\n" + code, encoding="utf-8")
    path.chmod(0o700)


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "website's checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "deploy site's.sh").write_text("printf 'ran:%s\\n' \"$CODESTER_DEPLOY_COMMIT\"\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Initial"], check=True)
    binary = tmp_path / "bin"
    binary.mkdir()
    # Use the inherited file descriptor to model flock where macOS lacks its CLI.
    executable(binary / "flock", "import fcntl\nfcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)\n")
    environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]}
    return repo, environment, binary


def run_wrapper(repo, environment, **changes):
    script = ServiceManager.repository_script({
        "update_mode": "script", "update_script_file": "scripts/deploy site's.sh",
        **changes,
    })
    return subprocess.run(["bash", "-c", script], cwd=repo, env=environment,
                          capture_output=True, text=True, timeout=10, check=False)


def test_wrapper_executes_committed_path_with_spaces(checkout):
    repo, environment, _ = checkout
    result = run_wrapper(repo, environment)
    assert result.returncode == 0, result.stderr
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert "ran:" + head in result.stdout


def test_wrapper_stops_on_dirty_missing_and_failed_pull(checkout):
    repo, environment, _ = checkout
    dirty = repo / "untracked.txt"
    dirty.write_text("uncommitted", encoding="utf-8")
    result = run_wrapper(repo, environment)
    assert result.returncode != 0 and "ran:" not in result.stdout
    dirty.unlink()
    result = run_wrapper(repo, environment, update_script_file="scripts/missing.sh")
    assert result.returncode != 0 and "ran:" not in result.stdout
    result = run_wrapper(repo, environment, update_pull=True)  # no configured upstream
    assert result.returncode != 0 and "ran:" not in result.stdout


def test_wrapper_stops_at_first_failed_command(checkout):
    repo, environment, _ = checkout
    (repo / "scripts" / "deploy site's.sh").write_text("false\necho SHOULD_NOT_RUN\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "Failing script"], check=True)
    result = run_wrapper(repo, environment)
    assert result.returncode != 0 and "SHOULD_NOT_RUN" not in result.stdout


def test_wrapper_respects_server_lock(checkout):
    import fcntl

    repo, environment, _ = checkout
    with (repo / ".git" / "codester-deploy.lock").open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_wrapper(repo, environment)
    assert result.returncode != 0
    assert "already running" in result.stderr
    assert "ran:" not in result.stdout


@pytest.mark.parametrize("failure", ["", "build", "test", "no-tests", "deploy", "health"])
def test_example_pipeline_gates_production_on_build_and_pytest(checkout, tmp_path, failure):
    repo, environment, binary = checkout
    log = tmp_path / "commands.jsonl"
    state = tmp_path / "deployed"
    environment.update(DEPLOY_TEST_LOG=str(log), DEPLOY_TEST_STATE=str(state), DEPLOY_TEST_FAILURE=failure)
    executable(binary / "docker", '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["DEPLOY_TEST_LOG"]).open("a") as log:
    log.write(json.dumps(args) + "\\n")
failure = os.environ["DEPLOY_TEST_FAILURE"]
state = Path(os.environ["DEPLOY_TEST_STATE"])
if args[0] == "build" and failure == "build": sys.exit(7)
if args[0] == "run" and failure in ("test", "no-tests"): sys.exit(5 if failure == "no-tests" else 1)
if args[:2] == ["image", "inspect"]: print("sha256:tested")
if args[0] == "inspect": print("sha256:tested" if state.exists() else "sha256:previous")
if args[0] == "compose" and "ps" in args: print("container-id")
if args[0] == "compose" and "up" in args:
    state.touch()
    if failure == "deploy": sys.exit(7)
''')
    executable(binary / "curl", '''import os, sys
sys.exit(22 if os.environ["DEPLOY_TEST_FAILURE"] == "health" else 0)
''')
    script = Path(__file__).parent.parent / "examples" / "deployment" / "deploy.sh"
    result = subprocess.run(["bash", str(script)], cwd=repo, env=environment,
                            capture_output=True, text=True, timeout=10, check=False)
    commands = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    deployed = any(command[0] == "compose" and "up" in command for command in commands)
    assert deployed == (failure not in {"build", "test", "no-tests"})
    assert (result.returncode == 0) == (not failure)
    if failure != "build":
        test = next(command for command in commands if command[0] == "run")
        assert test == ["run", "--rm", "--network", "none", "--entrypoint", "python", "sha256:tested", "-m", "pytest", "-q"]
    if deployed:
        deploy = next(command for command in commands if command[0] == "compose" and "up" in command)
        assert "--no-build" in deploy and "--wait" in deploy and "never" in deploy
    if not failure:
        assert "Deployment checks passed for commit" in result.stdout
