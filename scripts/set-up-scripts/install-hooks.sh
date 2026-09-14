#!/bin/sh
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
HOOKS_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "ERROR: .git/hooks not found. Run this from a cloned git repository." >&2
    exit 1
fi

cp "$SCRIPT_DIR/pre-commit.ps1" "$HOOKS_DIR/pre-commit.ps1"
cp "$SCRIPT_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"

echo "Installed canonical pre-commit hook and wrapper into .git/hooks/"
exit 0
