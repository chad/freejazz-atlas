#!/usr/bin/env bash
# Keep the Atlas honest over time.
#
# The corpus was assembled in a single research pass, which means its weakest
# property is *freshness*, not coverage. This script is the antidote, and it is
# meant to run unattended (launchd on macOS, cron elsewhere, CI on a schedule):
#
#   1. re-check every cited website          -> is the evidence still reachable?
#   2. re-crawl every source page            -> did the page change since we read it?
#   3. rebuild the site                      -> publish whatever changed
#   4. commit the data changes               -> the corpus keeps its own history
#   5. optionally redeploy                   -> the public site matches the data
#
# It never edits a score. A changed page or a dead link raises
# needs_human_review, which surfaces the venue in `atlas verify` and prints a
# warning box on its public page. Machines do the legwork; people do the judging.
#
# Usage: scripts/refresh.sh [--no-commit] [--no-push] [--deploy]

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="${ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

COMMIT=1
PUSH=1
DEPLOY=0
for arg in "$@"; do
  case "$arg" in
    --no-commit) COMMIT=0 ;;
    --no-push)   PUSH=0 ;;
    --deploy)    DEPLOY=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

CHANGED=0

log() { printf '\n=== %s — %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"; }

log "link health"
"$PY" -m atlas.cli linkcheck --write --workers 24

log "re-crawl sources (change detection)"
"$PY" -m atlas.cli recrawl --write --workers 16

log "validate"
"$PY" -m atlas.cli validate

log "rebuild site"
"$PY" -m atlas.cli build

log "verification queue (top of the list is where a human should look next)"
"$PY" -m atlas.cli verify --limit 10

if [ -n "$(git status --porcelain data DIRECTORY.md)" ]; then CHANGED=1; fi

if [ "$CHANGED" = 0 ]; then
  log "nothing changed"
elif [ "$COMMIT" = 0 ]; then
  log "$(git status --porcelain data | wc -l | tr -d ' ') record(s) changed, left uncommitted (--no-commit)"
else
  log "commit"
  git add data DIRECTORY.md
  # Summarise what actually moved, so the log is readable a year from now.
  changed=$(git diff --cached --name-only -- data | wc -l | tr -d ' ')
  git -c user.name="atlas-refresh" -c user.email="refresh@localhost" \
      commit -q -m "refresh: link health + source hashes for ${changed} record(s)" \
      -m "Automated sweep by scripts/refresh.sh. No scores changed; records whose
source page moved or disappeared are flagged needs_human_review."
  echo "committed ${changed} changed record(s)"
  if [ "$PUSH" = 1 ] && git remote get-url origin >/dev/null 2>&1; then
    log "push"
    git push -q origin HEAD && echo "pushed"
  fi
fi

# Redeploying is what keeps the public site from drifting away from the data on
# this machine. It only happens when something actually moved, so an unchanged
# week costs nothing.
if [ "$DEPLOY" = 1 ] && [ "$CHANGED" = 1 ] && command -v miren >/dev/null 2>&1; then
  log "redeploy to miren"
  miren deploy -f && echo "deployed"
elif [ "$DEPLOY" = 1 ]; then
  log "no data changes — skipping redeploy"
fi

log "done"
