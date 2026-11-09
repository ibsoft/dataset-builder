#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
SERVICE=datasetbuilder.service
MODE="${1:-install}"

usage() {
    echo "Usage: scripts/setup.sh [install [absolute-directory]|update]"
}

if [[ ( "$MODE" == install && $# -gt 2 ) || ( "$MODE" != install && $# -gt 1 ) ||
      ( "$MODE" != install && "$MODE" != configure && "$MODE" != update ) ]]; then
    usage >&2
    exit 2
fi

if [[ $EUID -eq 0 ]]; then
    echo "Run this script as the application user, not root; sudo is used for systemd." >&2
    exit 1
fi
for command in git python3 sudo systemctl flock; do
    command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
if [[ "$ROOT" =~ [[:space:]%\\\"] ]]; then
    echo "The installation path cannot contain whitespace, %, backslashes or quotes (systemd unit limitation)." >&2
    exit 1
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
    echo "Python 3.11 or newer is required." >&2
    exit 1
}
git rev-parse --is-inside-work-tree >/dev/null
lock_file="$(git rev-parse --git-path datasetbuilder-setup.lock)"
exec 9>"$lock_file"
flock -n 9 || { echo "Another setup or update is already running." >&2; exit 1; }

step() {
    if [[ -t 1 ]]; then
        printf '\033[1;36m%s\033[0m\n' "$1"
    else
        printf '%s\n' "$1"
    fi
}

run_step() {
    local message="$1" pid status frame=0
    local -a frames=('|' '/' '-' '\')
    shift
    if [[ ! -t 2 ]]; then
        step "$message"
        "$@"
        return
    fi
    "$@" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        printf '\r\033[1;36m%s %s\033[0m' "${frames[frame++ % 4]}" "$message" >&2
        sleep 0.1
    done
    if wait "$pid"; then status=0; else status=$?; fi
    printf '\r\033[2K' >&2
    if (( status == 0 )); then step "$message Done."; else echo "$message Failed." >&2; fi
    return "$status"
}

install_dependencies() {
    if [[ ! -x .venv/bin/python ]]; then
        python3 -m venv .venv
    fi
    .venv/bin/python -m pip install -r requirements.txt
}

validate_environment() {
    .venv/bin/python - <<'PY'
from dotenv import dotenv_values

values = dotenv_values(".env")
secret = values.get("SECRET_KEY") or ""
if len(secret) < 32 or secret in {"REPLACE_WITH_64_HEX_CHARACTERS", "dev-insecure-change-this-key"}:
    raise SystemExit("Set a unique SECRET_KEY of at least 32 characters in .env.")
PY
}

migrate() {
    env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" APP_ENV=production \
        .venv/bin/flask --app wsgi.py db upgrade
}

check_health() {
    local attempt
    for attempt in {1..20}; do
        if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:8000/healthz >/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "Service did not pass the HTTP/database health check; inspect the systemd logs." >&2
    return 1
}

check_nginx_site() {
    local site=/etc/nginx/sites-available/datasetbuilder
    local link=/etc/nginx/sites-enabled/datasetbuilder
    sudo test -d /etc/nginx/sites-available && sudo test -d /etc/nginx/sites-enabled || {
        echo "nginx sites-available and sites-enabled directories are required." >&2; return 1;
    }
    if sudo test -e "$site" || sudo test -L "$site" ||
       sudo test -e "$link" || sudo test -L "$link"; then
        echo "nginx site already exists; refusing to overwrite: $site or $link" >&2
        return 1
    fi
}

if [[ "$MODE" == install ]]; then
    missing=()
    command -v rsync >/dev/null || missing+=(rsync)
    command -v nginx >/dev/null || missing+=(nginx)
    command -v curl >/dev/null || missing+=(curl)
    python3 -c 'import ensurepip' >/dev/null 2>&1 || missing+=(python3-venv)
    if (( ${#missing[@]} )); then
        command -v apt-get >/dev/null || {
            echo "Install the missing dependencies manually: ${missing[*]}" >&2; exit 1;
        }
        read -r -p "Install missing packages (${missing[*]}) using apt? [y/N] " answer
        if [[ "$answer" != y && "$answer" != Y && "$answer" != yes && "$answer" != YES ]]; then
            echo "Install the missing dependencies and retry." >&2
            exit 1
        fi
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
    sudo test -r /opt/ssl/unixfor.crt && sudo test -r /opt/ssl/unixfor.key || {
        echo "The nginx TLS certificate or key in /opt/ssl is missing or unreadable." >&2
        exit 1
    }
    check_nginx_site
    if sudo test -e "/etc/systemd/system/$SERVICE" || sudo test -L "/etc/systemd/system/$SERVICE"; then
        echo "Service already exists; refusing to overwrite: $SERVICE" >&2
        exit 1
    fi
    if [[ $# -eq 2 ]]; then
        destination="$2"
    else
        printf 'Installation directory [/opt/dataset-builder]: ' >&2
        read -r destination || { echo "No installation directory provided." >&2; exit 1; }
        destination="${destination:-/opt/dataset-builder}"
    fi
    if [[ "$destination" != /* || "$destination" =~ [[:space:]%\\\"] ]]; then
        echo "The installation directory must be absolute and contain no whitespace, %, backslashes or quotes." >&2
        exit 1
    fi
    destination="$(realpath -m -- "$destination")"
    if [[ "$destination" == "$ROOT" || "$destination" == "$ROOT/"* || "$ROOT" == "$destination/"* ]]; then
        echo "The installation directory must be separate from the source checkout." >&2
        exit 1
    fi
    if [[ -e "$destination" || -L "$destination" ]]; then
        echo "Installation directory already exists; refusing to overwrite it: $destination" >&2
        exit 1
    fi
    branch="$(git symbolic-ref --quiet --short HEAD)" || {
        echo "Check out a branch before installing." >&2; exit 1;
    }
    remote="$(git config --get "branch.$branch.remote" || true)"
    remote="${remote:-origin}"
    [[ "$remote" != "." ]] || { echo "A remote upstream is required." >&2; exit 1; }
    remote_url="$(git remote get-url "$remote")" || {
        echo "Configure a Git remote before installing." >&2; exit 1;
    }
    merge_ref="$(git config --get "branch.$branch.merge" || true)"
    upstream_branch="${merge_ref#refs/heads/}"
    upstream_branch="${upstream_branch:-$branch}"
    step "Creating installation directory $destination..."
    sudo mkdir -p -- "$(dirname -- "$destination")"
    sudo mkdir -- "$destination"
    sudo chown "$(id -u):$(id -g)" "$destination"
    run_step "Copying the application..." git clone --no-checkout --no-hardlinks --branch "$branch" "$ROOT" "$destination"
    rsync -a --exclude=/.git --exclude=/.venv --exclude=/__pycache__ \
        --exclude=/.pytest_cache --exclude='*.pyc' "$ROOT/" "$destination/"
    git -C "$destination" remote set-url origin "$remote_url"
    git -C "$destination" fetch origin
    git -C "$destination" branch --set-upstream-to="origin/$upstream_branch" "$branch"
    step "Configuring the installed application..."
    exec bash "$destination/scripts/setup.sh" configure
fi

if [[ "$MODE" == configure ]]; then
    unit_path="/etc/systemd/system/$SERVICE"
    if sudo test -e "$unit_path" || sudo test -L "$unit_path"; then
        echo "Refusing to overwrite an existing service: $unit_path" >&2
        exit 1
    fi
    command -v nginx >/dev/null || { echo "nginx is required." >&2; exit 1; }
    sudo test -r /opt/ssl/unixfor.crt && sudo test -r /opt/ssl/unixfor.key || {
        echo "The nginx TLS certificate or key in /opt/ssl is missing or unreadable." >&2; exit 1;
    }
    check_nginx_site
    step "Preparing configuration..."
    if [[ ! -e .env ]]; then
        umask 077
        python3 - <<'PY'
from pathlib import Path
import secrets

template = Path(".env.example").read_text(encoding="utf-8")
Path(".env").write_text(
    template.replace("REPLACE_WITH_64_HEX_CHARACTERS", secrets.token_hex(32))
            .replace("COOKIE_SECURE=0", "COOKIE_SECURE=1"),
    encoding="utf-8",
)
PY
        echo "Created .env with a new secret key; review its settings before exposing the service."
    else
        echo "Keeping existing .env."
    fi
    nginx_site=/etc/nginx/sites-available/datasetbuilder
    nginx_link=/etc/nginx/sites-enabled/datasetbuilder
    run_step "Installing Python dependencies..." install_dependencies
    validate_environment
    run_step "Applying database migrations..." migrate
    step "Installing systemd service..."
    unit="$(mktemp)"
    trap 'status=$?; rm -f -- "$unit"; if (( status != 0 )); then echo "Setup failed; the service may be stopped." >&2; fi' EXIT
    cat > "$unit" <<EOF
# Managed by DatasetBuilder setup.sh
[Unit]
Description=DatasetBuilder
After=network.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$ROOT
EnvironmentFile=$ROOT/.env
ExecStart=/usr/bin/env APP_ENV=production $ROOT/.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 2 --worker-class gthread --timeout 60 --access-logfile - --error-logfile - wsgi:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo install -m 0644 "$unit" "$unit_path"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE"
    sudo systemctl restart "$SERVICE"
    systemctl is-active --quiet "$SERVICE"
    run_step "Checking application health..." check_health
    step "Installing nginx site..."
    sudo install -m 0644 "$ROOT/scripts/datasetbuilder.nginx.conf" "$nginx_site"
    if ! sudo ln -s "$nginx_site" "$nginx_link"; then
        sudo rm -f -- "$nginx_site"
        echo "Could not enable nginx site; the new site was removed." >&2
        exit 1
    fi
    if ! sudo nginx -t; then
        sudo rm -f -- "$nginx_link" "$nginx_site"
        echo "nginx validation failed; the new site was removed and nginx was not reloaded." >&2
        exit 1
    fi
    sudo systemctl reload nginx
    echo "Setup complete. Create an administrator with:"
    echo "  cd $ROOT && APP_ENV=production .venv/bin/flask --app wsgi.py create-admin"
    echo "Control the service with: $ROOT/datase-ctl {start|stop|status|logs|update|debug}"
    echo "Service: https://dataset-builder.unixfor.gr"
    exit 0
fi

[[ -f .env && -x .venv/bin/python ]] || {
    echo "Install the application before updating." >&2
    exit 1
}
git diff --cached --quiet || { echo "Commit or unstage changes before updating." >&2; exit 1; }
if [[ -n "$(git status --porcelain --untracked-files=no -- . ':(exclude)data' ':(exclude)data/**')" ]]; then
    echo "Commit or discard tracked changes outside data/ before updating." >&2
    exit 1
fi
upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')" || {
    echo "Configure an upstream branch before updating." >&2
    exit 1
}
step "Fetching $upstream..."
git fetch
git merge-base --is-ancestor HEAD '@{upstream}' || {
    echo "The upstream is not a fast-forward of this branch; no changes were made." >&2
    exit 1
}
if [[ -n "$(git diff --name-only HEAD '@{upstream}' -- .env .venv)" ]]; then
    echo "The update changes .env or .venv; refusing to overwrite local configuration." >&2
    exit 1
fi
.venv/bin/python - <<'PY'
from pathlib import Path
import subprocess
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

root = Path.cwd()
values = dotenv_values(".env")
paths = [Path(values.get("KB_DIRECTORY") or root / "data/knowledge_base")]
url = make_url(values.get("DATABASE_URL") or f"sqlite:///{root / 'data/datasetbuilder.sqlite'}")
if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
    database = Path(url.database)
    paths.append(database if database.is_absolute() else root / "instance" / database)
protected = [path.resolve() for path in paths]
changed = subprocess.check_output(
    ["git", "diff", "--name-only", "-z", "HEAD", "@{upstream}"]
).split(b"\0")
for name in filter(None, changed):
    path = (root / name.decode("utf-8", "surrogateescape")).resolve()
    if any(path == item or item in path.parents or path in item.parents for item in protected):
        if root / "data" not in path.parents and path != root / "data":
            raise SystemExit(f"Update changes configured database or knowledge files: {path}")
PY
if [[ -e data && ( ! -d data || -L data ) ]]; then
    echo "data must be a real directory, not a file or symbolic link." >&2
    exit 1
fi
backup="$(mktemp -d "$ROOT/.datasetbuilder-update.XXXXXXXX")"
data_saved=0
data_existed=0
service_start_attempted=0
restore_data() {
    if (( data_saved )); then
        if [[ -e data || -L data ]]; then
            mv -- data "$backup/upstream-data" || return 1
        fi
        if (( data_existed )); then
            mv -- "$backup/data" data || return 1
        fi
        data_saved=0
    fi
}
cleanup() {
    status=$?
    trap - EXIT
    if ! restore_data; then
        echo "ERROR: Could not restore data. Recover it from $backup/data." >&2
        exit 1
    fi
    rm -rf -- "$backup"
    if (( status != 0 )); then
        if (( service_start_attempted )) && ! sudo systemctl stop "$SERVICE"; then
            echo "ERROR: Could not stop the service after the failed update; check its status." >&2
        else
            echo "Update failed; the service remains stopped. Check the error and restore from backup if needed." >&2
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
step "Stopping the service and protecting local data..."
sudo systemctl stop "$SERVICE"
if [[ -d data ]]; then
    mv -- data "$backup/data"
    data_existed=1
fi
data_saved=1
if [[ -n "$(git ls-files -- data)" ]]; then
    git restore --source=HEAD --worktree -- data
fi
run_step "Updating application files..." git merge --ff-only '@{upstream}'
restore_data
run_step "Installing Python dependencies..." install_dependencies
validate_environment
run_step "Applying database migrations..." migrate
step "Starting the service..."
service_start_attempted=1
sudo systemctl start "$SERVICE"
systemctl is-active --quiet "$SERVICE"
run_step "Checking application health..." check_health
echo "Update complete. Check: sudo systemctl status $SERVICE"
