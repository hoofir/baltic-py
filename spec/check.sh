#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
	echo "usage: $0 OAS_URL REPORTS_URL SPEC REPORTS PIN_EXAMPLES" >&2
	exit 2
fi

oas_url=$1
reports_url=$2
spec_file=$3
reports_file=$4
pin_examples=$5

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

curl -sSf "$oas_url" -o "$tmp/spec.raw" || { echo "failed to fetch OpenAPI spec" >&2; exit 1; }
curl -sSf "$reports_url" -o "$tmp/reports.raw" || { echo "failed to fetch reports metadata" >&2; exit 1; }
uv run python -m json.tool "$tmp/spec.raw" > "$tmp/spec.pretty" || { echo "failed to parse OpenAPI spec JSON" >&2; exit 1; }
uv run python -m json.tool "$tmp/reports.raw" > "$tmp/reports.live" || { echo "failed to parse reports metadata JSON" >&2; exit 1; }
sed -E "$pin_examples" < "$tmp/spec.pretty" > "$tmp/spec.live"

check_drift() {
	if diff -q "$1" "$2" > /dev/null; then return 0; else status=$?; fi
	if [ "$status" -eq 1 ]; then
		echo "spec drifted: run 'make spec catalog'" >&2
	else
		echo "failed to compare $1 and $2" >&2
	fi
	return "$status"
}

check_drift "$spec_file" "$tmp/spec.live"
check_drift "$reports_file" "$tmp/reports.live"
echo "spec is up to date"