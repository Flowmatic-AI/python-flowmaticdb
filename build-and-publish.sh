#!/usr/bin/env bash
set -euo pipefail

# ─── Colors ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
fail() { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# Always operate from the project root, regardless of where we were invoked from
cd "$(dirname "${BASH_SOURCE[0]}")"

# ─── Check prerequisites ───
command -v python3  >/dev/null 2>&1 || fail "python3 not found — install Python 3.11+"
python3 -m pip --version >/dev/null 2>&1 || fail "pip not available for $(command -v python3)"

# ─── Load .env (PYPI_API_KEY) ───
if [[ ! -f .env ]]; then
    fail ".env file not found — create it with PYPI_API_KEY=pypi-<your-token>"
fi

# Read only the key variable (safe subset), stripping quotes and any trailing CR
PYPI_API_KEY=$(grep '^PYPI_API_KEY=' .env | head -1 | cut -d'=' -f2- | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//')

if [[ -z "$PYPI_API_KEY" ]]; then
    fail "PYPI_API_KEY not set in .env"
fi

# ─── Read the version we are about to publish ───
VERSION=$(grep -E '^version *=' pyproject.toml | head -1 | cut -d'"' -f2)
[[ -n "$VERSION" ]] || fail "Could not read version from pyproject.toml"

# ─── Install build tools if missing ───
python3 -m pip install --quiet build twine

# ─── Clean stale artifacts ───
# dist/ accumulates every previous build; uploading those re-sends versions that
# are already on PyPI, which fails the whole upload with "File already exists".
log "Cleaning dist/ ..."
rm -rf dist build src/*.egg-info

log "Building package $VERSION ..."
python3 -m build

ARTIFACTS=("dist/flowmaticdb-$VERSION.tar.gz" "dist/flowmaticdb-$VERSION-py3-none-any.whl")
for artifact in "${ARTIFACTS[@]}"; do
    [[ -f "$artifact" ]] || fail "Expected build artifact not found: $artifact"
done

log "Checking package with twine..."
python3 -m twine check "${ARTIFACTS[@]}"

# ─── Confirm before publishing ───
echo ""
warn "This will publish to PyPI (pypi.org)!"
echo "  Package: flowmaticdb"
echo "  Version: $VERSION"
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    warn "Aborted."
    exit 0
fi

# ─── Publish ───
log "Uploading to PyPI..."
python3 -m twine upload "${ARTIFACTS[@]}" \
    --username __token__ \
    --password "$PYPI_API_KEY"

log "Done! Package published to PyPI."
