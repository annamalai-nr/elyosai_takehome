BASE="https://elyos-interview-907656039105.europe-west2.run.app"
for path in "/openapi.json" "/docs" "/redoc" "/" "/health" "/healthz" "/status" "/metrics" "/version" "/api" "/v1"; do
  echo ""
  echo "=========================================="
  echo "GET $BASE$path"
  echo "=========================================="
  curl -sS -i --max-time 10 "$BASE$path" | head -300
done