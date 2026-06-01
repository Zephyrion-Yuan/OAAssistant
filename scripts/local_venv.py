import os
import subprocess
import sys
import time
from pathlib import Path
from venv import EnvBuilder


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def npm_command():
    return "npm.cmd" if os.name == "nt" else "npm"


def venv_bin_dir():
    return VENV / ("Scripts" if os.name == "nt" else "bin")


def venv_env():
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(VENV)
    env["PATH"] = str(venv_bin_dir()) + os.pathsep + env.get("PATH", "")
    env.setdefault("MEGANT_EDGE_PROFILE_MODE", "isolated")
    env.setdefault("MEGANT_BROWSER_CHANNEL", "msedge")
    return env


def run(command, env=None):
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env or os.environ.copy(), check=True)


def stop_port_owner(port):
    if os.name != "nt":
        return
    ps = (
        "$port = " + str(port) + "; "
        "$conns = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue; "
        "foreach ($c in $conns) { "
        "  $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; "
        "  if ($p -and $p.ProcessName -eq 'node') { "
        "    Write-Output ('Stopping node process ' + $p.Id + ' on port ' + $port); "
        "    Stop-Process -Id $p.Id -Force; "
        "  } "
        "}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", ps],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout.strip():
        print(completed.stdout.strip(), flush=True)
    if completed.returncode != 0 and completed.stderr.strip():
        print(f"Port cleanup warning: {completed.stderr.strip()}", flush=True)
    time.sleep(1)


def ensure_venv():
    marker = VENV / "pyvenv.cfg"
    if marker.exists():
        return
    print(f"Creating {VENV}", flush=True)
    EnvBuilder(with_pip=True, clear=False).create(VENV)


def setup():
    ensure_venv()
    run([npm_command(), "install"], env=venv_env())


def start():
    ensure_venv()
    if not (ROOT / "node_modules").exists():
        run([npm_command(), "install"], env=venv_env())
    stop_port_owner(int(os.environ.get("PORT", "8787")))
    run([npm_command(), "start"], env=venv_env())


def sso_start():
    ensure_venv()
    if not (ROOT / "node_modules").exists():
        run([npm_command(), "install"], env=venv_env())
    env = venv_env()
    env["MEGANT_EDGE_PROFILE_MODE"] = "sso-handoff"
    env.setdefault("MEGANT_EDGE_PROFILE_NAME", "MEGAntBot")
    env["MEGANT_AUTO_LAUNCH_EDGE"] = "1"
    env.setdefault("MEGANT_STARTUP_URL", f"http://127.0.0.1:{env.get('PORT', '8787')}/")
    stop_port_owner(int(env.get("PORT", "8787")))
    run([npm_command(), "start"], env=env)


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    if command == "setup":
        setup()
    elif command == "start":
        start()
    elif command == "sso-start":
        sso_start()
    else:
        raise SystemExit(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
