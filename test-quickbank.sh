#!/bin/bash
# Simple smoke test for QuickBank
# Usage: ./test-quickbank.sh [URL]

URL=${1:-http://localhost:8080}

echo "Testing QuickBank at $URL"
echo "================================"

echo -n "Health check ... "
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
[ "$STATUS" = "200" ] && echo "OK ($STATUS)" || echo "FAIL ($STATUS)"

echo -n "Home page ... "
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/")
[ "$STATUS" = "200" ] && echo "OK ($STATUS)" || echo "FAIL ($STATUS)"

echo -n "Deposit \$100 ... "
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -d "amount=100" "$URL/deposit")
[ "$STATUS" = "302" ] && echo "OK (redirect $STATUS)" || echo "FAIL ($STATUS)"

echo -n "Withdraw \$50 ... "
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST -d "amount=50" "$URL/withdraw")
[ "$STATUS" = "302" ] && echo "OK (redirect $STATUS)" || echo "FAIL ($STATUS)"

echo -n "Rate limit status ... "
RLSTATUS=$(curl -s "$URL/admin/ratelimit/status")
echo "$RLSTATUS"

echo ""
echo "Verify balance:"
curl -s "$URL/health"
echo ""

echo "================================"
echo "Done."
