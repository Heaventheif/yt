# bench/
- `starve.py APP_DIR THREADS` — يحاكي 14 استخراجاً بطيئاً ويقيس هل يبقى `/health` يستجيب (تجويع الخيوط).
- `stream_bench.py APP_DIR` — زمن الإقلاع، ذاكرة الـ worker، وكلفة CPU لكل MB عند التمرير (مصدر محلي بلا TLS).
- لقياس حقيقي على Render: `hey -z 60s -c 8 "https://<app>/health"` و `hey -n 20 -c 2 -H "X-API-Key: $KEY" "https://<app>/info?url=<video>"` وراقب Metrics (CPU/Memory) في لوحة Render.
