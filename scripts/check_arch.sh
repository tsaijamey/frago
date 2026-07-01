#!/usr/bin/env bash
# check_arch.sh — run import-linter architectural contracts.
#
# Phase 0: REPORT-ONLY. The repo currently violates several contracts (known
# dependency cycles via lazy imports). We print the full report and the count of
# broken contracts, but ALWAYS exit 0 so CI is not gated on the debt baseline.
# The broken-contract count is the technical-debt baseline; Phase 7 flips this
# to enforced (`exit ${rc}`) once cycles are removed.
#
# Usage: scripts/check_arch.sh
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

echo "== frago architecture contracts (import-linter, Phase 0 report-only) =="
echo

# Capture output and exit code without aborting on contract breakage.
output="$(uv run lint-imports 2>&1)"
rc=$?

echo "${output}"
echo
echo "---------------------------------------------------------------"

broken="$(printf '%s\n' "${output}" | grep -c 'BROKEN')"
kept="$(printf '%s\n' "${output}" | grep -c 'KEPT')"
echo "Contracts KEPT:   ${kept}"
echo "Contracts BROKEN: ${broken}  (Phase 0 debt baseline)"
echo "lint-imports exit code: ${rc} (suppressed; report-only)"

# Phase 0: never fail CI on the baseline.
exit 0
