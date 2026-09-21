#!/usr/bin/env bash
# Set up one worktree per workstream so several Claude sessions can build at
# once without sharing a test database, a dev-server port, or a checkout.
# See docs/roadmap/workstreams-2026-09.md §4.
#
#   scripts/worktree.sh <name>        -> .worktrees/<name> on branch feat/<name>
#
# Idempotent: re-running on an existing worktree only refreshes the links
# and the env file. Never touches other worktrees.
set -euo pipefail

name="${1:?usage: scripts/worktree.sh <name>}"
case "$name" in *[!a-z0-9-]*) echo "name must be lowercase letters, digits, dashes" >&2; exit 1;; esac

root="$(git rev-parse --show-toplevel)"
cd "$root"
dir=".worktrees/$name"
branch="feat/$name"

if [ ! -d "$dir" ]; then
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    git worktree add "$dir" "$branch"
  else
    git worktree add "$dir" -b "$branch"
  fi
fi

# Shared, read-only dependencies: link rather than reinstall. The corpus is
# NDA'd and gitignored; the link keeps corpus-gated tests running here.
for link in node_modules .enginevenv bid_examples; do
  [ -e "$root/$link" ] && [ ! -e "$dir/$link" ] && ln -s "../../$link" "$dir/$link"
done

# Own env: same dev database, its own test database. The suite creates and
# drops TEST_DATABASE_URL's database, so two worktrees on one name would
# drop each other's tables mid-run.
if [ -f "$root/api/.env" ]; then
  sed -E "s#(TEST_DATABASE_URL=.*/)takeoff_test[a-z0-9_]*#\1takeoff_test_${name//-/_}#" "$root/api/.env" > "$dir/api/.env"
fi

# A dev-server port nobody else in .worktrees is using: 5173 + position.
n=$(git worktree list --porcelain | grep -c '^worktree .*/\.worktrees/' || true)
port=$((5173 + n))

cat <<EOF
Worktree ready: $dir  (branch $branch)
  backend tests : cd $dir/api && ../.enginevenv/bin/python -m pytest -q
  test database : takeoff_test_${name//-/_}   (set in $dir/api/.env)
  dev server    : cd $dir && npm run dev -- --port $port
Open a new Claude session on this repo and tell it to work in $dir.
EOF
