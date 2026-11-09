import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.sh"
CONTROL = Path(__file__).resolve().parents[1] / "datase-ctl"
NGINX = Path(__file__).resolve().parents[1] / "scripts" / "datasetbuilder.nginx.conf"


def run(*args, cwd, env=None, check=True, input=None):
    return subprocess.run(
        args, cwd=cwd, env=env, check=check, text=True, capture_output=True, input=input
    )


def write(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    run("git", "init", "-b", "main", cwd=source)
    run("git", "config", "user.email", "test@example.com", cwd=source)
    run("git", "config", "user.name", "Test", cwd=source)
    write(source / "scripts/setup.sh", SCRIPT.read_text(encoding="utf-8"))
    write(source / "scripts/datasetbuilder.nginx.conf", NGINX.read_text(encoding="utf-8"))
    write(source / "datase-ctl", CONTROL.read_text(encoding="utf-8"), executable=True)
    write(source / ".gitignore", ".env\n.venv/\n")
    write(source / "requirements.txt", "")
    write(source / "data/db", "original database")
    write(source / "data/deleted", "original file")
    write(source / "app.txt", "old code")
    run("git", "add", ".", cwd=source)
    run("git", "commit", "-m", "initial", cwd=source)
    remote = tmp_path / "remote.git"
    run("git", "init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    run("git", "remote", "add", "origin", str(remote), cwd=source)
    run("git", "push", "-u", "origin", "main", cwd=source)
    checkout = tmp_path / "checkout"
    run("git", "clone", str(remote), str(checkout), cwd=tmp_path)
    write(checkout / ".env", "SECRET_KEY=" + "a" * 64 + "\n")
    write(
        checkout / ".venv/bin/python",
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi\n'
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        executable=True,
    )
    write(
        checkout / ".venv/bin/flask",
        "#!/bin/sh\n[ ! -f .fail-migration ]\n",
        executable=True,
    )
    bin_dir = tmp_path / "bin"
    write(
        bin_dir / "sudo",
        '#!/bin/sh\n'
        'if [ "$1" = test ]; then case "$2" in -r|-d) exit 0;; -e|-L) exit 1;; esac; fi\n'
        'if [ "$1" = install ]; then case "$5" in '
        '*/datasetbuilder.service) cp "$4" .installed-unit; exit;; '
        '*/sites-available/datasetbuilder) cp "$4" .installed-nginx; exit;; esac; fi\n'
        'if [ "$1" = ln ]; then exit 0; fi\n'
        'exec "$@"\n',
        executable=True,
    )
    write(bin_dir / "nginx", "#!/bin/sh\nexit 0\n", executable=True)
    write(bin_dir / "curl", '#!/bin/sh\nprintf "{\\"status\\":\\"ok\\"}\\n"\n', executable=True)
    write(
        bin_dir / "systemctl",
        '#!/bin/sh\nprintf "%s\\n" "$*" >> .service-log\n'
        'if [ "$1" = is-active ] && ! grep -Eq "^(start|restart) datasetbuilder" .service-log; '
        'then exit 3; fi\n',
        executable=True,
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return source, checkout, env


def publish(source):
    run("git", "add", "-A", cwd=source)
    run("git", "commit", "-m", "update", cwd=source)
    run("git", "push", cwd=source)


def update(checkout, env):
    return run("bash", "scripts/setup.sh", "update", cwd=checkout, env=env, check=False)


def test_update_preserves_all_local_data_and_env(deployment):
    source, checkout, env = deployment
    write(source / "data/db", "upstream database")
    write(source / "data/new", "upstream file")
    write(source / "app.txt", "new code")
    publish(source)
    write(checkout / "data/db", "local database")
    (checkout / "data/deleted").unlink()
    write(checkout / "data/local", "local file")
    original_env = (checkout / ".env").read_bytes()

    result = update(checkout, env)

    assert result.returncode == 0, result.stderr
    assert (checkout / "app.txt").read_text() == "new code"
    assert (checkout / "data/db").read_text() == "local database"
    assert (checkout / "data/local").read_text() == "local file"
    assert not (checkout / "data/deleted").exists()
    assert not (checkout / "data/new").exists()
    assert (checkout / ".env").read_bytes() == original_env
    assert (checkout / ".service-log").read_text().splitlines() == [
        "stop datasetbuilder.service",
        "start datasetbuilder.service",
        "is-active --quiet datasetbuilder.service",
    ]


def test_failed_migration_preserves_data_and_leaves_service_stopped(deployment):
    source, checkout, env = deployment
    write(source / "app.txt", "new code")
    publish(source)
    write(checkout / "data/db", "local database")
    write(checkout / ".fail-migration", "")

    result = update(checkout, env)

    assert result.returncode != 0
    assert "service remains stopped" in result.stderr
    assert (checkout / "data/db").read_text() == "local database"
    assert (checkout / ".service-log").read_text().splitlines() == [
        "stop datasetbuilder.service"
    ]


def test_update_rejects_changes_to_configured_database_outside_data(deployment):
    source, checkout, env = deployment
    database = checkout / "instance" / "custom.sqlite"
    write(database, "existing database")
    write(
        checkout / ".env",
        "SECRET_KEY=" + "a" * 64 + f"\nDATABASE_URL=sqlite:///{database}\n",
    )
    write(source / "instance/custom.sqlite", "upstream database")
    publish(source)

    result = update(checkout, env)

    assert result.returncode != 0
    assert "configured database or knowledge files" in result.stderr
    assert database.read_text() == "existing database"
    assert not (checkout / ".service-log").exists()


def test_update_rejects_tracked_code_changes(deployment):
    _, checkout, env = deployment
    write(checkout / "app.txt", "local edit")

    result = update(checkout, env)

    assert result.returncode != 0
    assert "tracked changes outside data/" in result.stderr
    assert (checkout / "app.txt").read_text() == "local edit"
    assert not (checkout / ".service-log").exists()


def test_update_preserves_absent_data_directory(deployment):
    source, checkout, env = deployment
    for path in (checkout / "data").iterdir():
        path.unlink()
    (checkout / "data").rmdir()
    write(source / "app.txt", "new code")
    publish(source)

    result = update(checkout, env)

    assert result.returncode == 0, result.stderr
    assert not (checkout / "data").exists()


def test_update_rejects_non_fast_forward(deployment):
    source, checkout, env = deployment
    run("git", "config", "user.email", "test@example.com", cwd=checkout)
    run("git", "config", "user.name", "Test", cwd=checkout)
    write(checkout / "app.txt", "local commit")
    run("git", "add", "app.txt", cwd=checkout)
    run("git", "commit", "-m", "local change", cwd=checkout)
    write(source / "app.txt", "upstream commit")
    publish(source)

    result = update(checkout, env)

    assert result.returncode != 0
    assert "not a fast-forward" in result.stderr
    assert (checkout / "app.txt").read_text() == "local commit"
    assert not (checkout / ".service-log").exists()


def test_setup_preserves_configuration_and_installs_service(deployment):
    _, checkout, env = deployment
    original_env = (checkout / ".env").read_bytes()

    result = run("bash", "scripts/setup.sh", "configure", cwd=checkout, env=env, check=False)

    assert result.returncode == 0, result.stderr
    assert (checkout / ".env").read_bytes() == original_env
    unit = (checkout / ".installed-unit").read_text()
    assert f"WorkingDirectory={checkout}" in unit
    assert f"EnvironmentFile={checkout}/.env" in unit
    assert "ExecStart=/usr/bin/env APP_ENV=production " in unit
    assert "--bind 127.0.0.1:8000" in unit
    assert (checkout / ".service-log").read_text().splitlines() == [
        "daemon-reload",
        "enable datasetbuilder.service",
        "restart datasetbuilder.service",
        "is-active --quiet datasetbuilder.service",
        "reload nginx",
    ]
    assert (checkout / ".installed-nginx").read_text() == NGINX.read_text()


def test_setup_generates_secret_for_new_configuration(deployment):
    _, checkout, env = deployment
    (checkout / ".env").unlink()
    write(checkout / ".env.example", "SECRET_KEY=REPLACE_WITH_64_HEX_CHARACTERS\nCOOKIE_SECURE=0\n")

    result = run("bash", "scripts/setup.sh", "configure", cwd=checkout, env=env, check=False)

    assert result.returncode == 0, result.stderr
    secret = (checkout / ".env").read_text().splitlines()[0].split("=", 1)[1]
    assert len(secret) == 64
    assert all(character in "0123456789abcdef" for character in secret)
    assert "COOKIE_SECURE=1" in (checkout / ".env").read_text()
    assert (checkout / ".env").stat().st_mode & 0o077 == 0


def test_failed_merge_restores_data_and_leaves_service_stopped(deployment):
    source, checkout, env = deployment
    write(source / "new.txt", "upstream")
    publish(source)
    write(checkout / "new.txt", "local untracked file")
    write(checkout / "data/db", "local database")

    result = update(checkout, env)

    assert result.returncode != 0
    assert (checkout / "data/db").read_text() == "local database"
    assert (checkout / "new.txt").read_text() == "local untracked file"
    assert (checkout / ".service-log").read_text().splitlines() == [
        "stop datasetbuilder.service"
    ]


def test_install_copies_checkout_and_configures_service(deployment, tmp_path):
    source, checkout, env = deployment
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    write(
        bin_dir / "python3",
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
        '  mkdir -p "$3/bin"\n'
        f'  cp {shlex.quote(str(checkout / ".venv/bin/python"))} "$3/bin/python"\n'
        f'  cp {shlex.quote(str(checkout / ".venv/bin/flask"))} "$3/bin/flask"\n'
        "  exit\nfi\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n',
        executable=True,
    )
    write(checkout / "data/db", "local database")
    write(checkout / "data/local", "local knowledge")
    destination = tmp_path / "installed"

    result = run("bash", "scripts/setup.sh", "install", str(destination),
                 cwd=checkout, env=env, check=False)

    assert result.returncode == 0, result.stderr
    assert (destination / "data/db").read_text() == "local database"
    assert (destination / "data/local").read_text() == "local knowledge"
    assert (destination / ".env").read_bytes() == (checkout / ".env").read_bytes()
    assert (destination / ".venv/bin/python").is_file()
    assert (destination / "datase-ctl").stat().st_mode & 0o111
    assert f"WorkingDirectory={destination}" in (destination / ".installed-unit").read_text()
    assert (destination / ".installed-nginx").read_text() == NGINX.read_text()
    remote = run("git", "remote", "get-url", "origin", cwd=destination).stdout.strip()
    assert remote == str(tmp_path / "remote.git")
    assert run("git", "rev-parse", "--abbrev-ref", "@{upstream}", cwd=destination).stdout.strip() == "origin/main"
    assert (source / "data/db").read_text() == "original database"


def test_install_refuses_existing_destination(deployment, tmp_path):
    _, checkout, env = deployment
    destination = tmp_path / "existing"
    destination.mkdir()
    write(destination / "keep", "important")
    result = run("bash", "scripts/setup.sh", "install", str(destination),
                 cwd=checkout, env=env, check=False)
    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert (destination / "keep").read_text() == "important"


def test_install_prompts_for_directory(deployment, tmp_path):
    _, checkout, env = deployment
    destination = tmp_path / "existing"
    destination.mkdir()
    result = run("bash", "scripts/setup.sh", cwd=checkout, env=env,
                 input=f"{destination}\n", check=False)
    assert result.returncode != 0
    assert "Installation directory [/opt/dataset-builder]" in result.stderr
    assert "already exists" in result.stderr


def test_nginx_failure_removes_site_and_skips_reload(deployment):
    _, checkout, env = deployment
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    write(bin_dir / "nginx", "#!/bin/sh\nexit 1\n", executable=True)
    sudo = bin_dir / "sudo"
    sudo.write_text(sudo.read_text().replace(
        'if [ "$1" = ln ]; then exit 0; fi\n',
        'if [ "$1" = ln ]; then exit 0; fi\n'
        'if [ "$1" = rm ]; then printf "%s\\n" "$*" >> .cleanup-log; exit 0; fi\n',
    ))
    result = run("bash", "scripts/setup.sh", "configure", cwd=checkout, env=env, check=False)
    assert result.returncode != 0
    assert "nginx validation failed" in result.stderr
    assert "reload nginx" not in (checkout / ".service-log").read_text()
    assert "/etc/nginx/sites-enabled/datasetbuilder" in (checkout / ".cleanup-log").read_text()


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("start", "start datasetbuilder.service"),
        ("stop", "stop datasetbuilder.service"),
        ("status", "--no-pager status datasetbuilder.service"),
    ],
)
def test_control_commands(deployment, command, expected):
    _, checkout, env = deployment
    result = run("bash", "datase-ctl", command, cwd=checkout, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert (checkout / ".service-log").read_text().strip() == expected


def test_control_logs_and_debug(deployment):
    _, checkout, env = deployment
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    write(bin_dir / "journalctl", '#!/bin/sh\nprintf "%s\\n" "$*" >> .journal-log\n', executable=True)
    write(bin_dir / "curl", '#!/bin/sh\nprintf "{\\"status\\":\\"ok\\"}\\n"\n', executable=True)
    result = run("bash", "datase-ctl", "logs", cwd=checkout, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert (checkout / ".journal-log").read_text().strip() == "--no-pager -u datasetbuilder.service -n 100 -f"
    result = run("bash", "datase-ctl", "debug", cwd=checkout, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert "Database check:" in result.stdout
    assert '{"status":"ok"}' in result.stdout


def test_control_update_uses_installed_checkout(deployment):
    source, checkout, env = deployment
    write(source / "app.txt", "updated")
    publish(source)
    result = run("bash", "datase-ctl", "update", cwd=checkout, env=env, check=False)
    assert result.returncode == 0, result.stderr
    assert (checkout / "app.txt").read_text() == "updated"
