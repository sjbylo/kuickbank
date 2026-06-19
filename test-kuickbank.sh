#!/bin/bash
# Simple smoke test for KuickBank
# Usage: ./test-kuickbank.sh [URL]
# Uses -sk so the script works with self-signed certs (OpenShift routes).

URL=${1:-http://localhost:8080}
CURL="curl -sk"

# Resolve the final URL (follow any HTTP→HTTPS redirect) for GET requests
BASE=$($CURL -o /dev/null -w "%{url_effective}" -L "$URL/health")
BASE=${BASE%/health}

echo "Testing KuickBank at $URL (effective: $BASE)"
echo "================================"

echo -n "Health check ... "
STATUS=$($CURL -o /dev/null -w "%{http_code}" "$BASE/health")
[ "$STATUS" = "200" ] && echo "OK ($STATUS)" || echo "FAIL ($STATUS)"

echo -n "Home page ... "
STATUS=$($CURL -o /dev/null -w "%{http_code}" "$BASE/")
[ "$STATUS" = "200" ] && echo "OK ($STATUS)" || echo "FAIL ($STATUS)"

echo -n "Deposit \$100 ... "
STATUS=$($CURL -o /dev/null -w "%{http_code}" -X POST -d "amount=100" "$BASE/deposit")
[ "$STATUS" = "302" ] && echo "OK (redirect $STATUS)" || echo "FAIL ($STATUS)"

echo -n "Withdraw \$50 ... "
STATUS=$($CURL -o /dev/null -w "%{http_code}" -X POST -d "amount=50" "$BASE/withdraw")
[ "$STATUS" = "302" ] && echo "OK (redirect $STATUS)" || echo "FAIL ($STATUS)"

echo -n "Rate limit status ... "
RLSTATUS=$($CURL "$BASE/admin/ratelimit/status")
echo "$RLSTATUS"

echo ""
echo "Verify balance:"
$CURL "$BASE/health"
echo ""

echo "================================"
echo "Done."
