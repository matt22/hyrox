#!/usr/bin/env bash
# Commit and push the given state paths, if they changed.
set -euo pipefail
git add -f -- "$@"
if git diff --cached --quiet; then exit 0; fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "chore: update ticket monitor state [skip ci]"
# Another push can land while Playwright is driving the ticket shop.
git pull --rebase --autostash origin "$GITHUB_REF_NAME"
git push origin "HEAD:$GITHUB_REF_NAME"
