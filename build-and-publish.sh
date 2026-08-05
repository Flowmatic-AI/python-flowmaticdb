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

# ─── Check prerequisites ───
command -v python3  >/dev/null 2>&1 || fail "python3 not found — install Python 3.11+"
command -v pip      >/dev/null 2>&1 || fail "pip not found"

# ─── Load .env (PYPI_API_KEY) ───
if [[ ! -f .env ]]; then
    fail ".env file not found — create it with PYPI_API_KEY=pypi-<your-token>"
fi

# Source only the key variable (safe subset)
PYPI_API_KEY=$(grep '^PYPI_API_KEY=' .env | cut -d'=' -f2-)

if [[ -z "$PYPI_API_KEY" ]]; then
    fail "PYPI_API_KEY not set in .env"
fi

# ─── Install build tools if missing ───
pip install --quiet build twine 2>/dev/null || pip install build twine

log "Building package..."
python3 -m build

log "Checking package with twine..."
twine check dist/*

# ─── Confirm before publishing ───
echo ""
warn "This will publish to PyPI (pypi.org)!"
echo "  Package: flowmaticdb"
grep '^version' pyproject.toml | tr -d ' '
echo ""
read -rp "Continue? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    warn "Aborted."
    exit 0
fi

# ─── Publish ───
log "Uploading to PyPI..."
twine upload dist/* \
    --username __token__ \
    --password "$PYPI_API_KEY"

log "Done! Package published to PyPI."
