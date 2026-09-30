#!/bin/sh
set -e

if [ "${AUTO_UPDATE:-0}" = "1" ]; then
  pip install -q -U "yt-dlp[default]" || true
fi

if [ "${ENABLE_POT:-1}" = "1" ]; then
  node /opt/bgutil/server/build/main.js &
fi

# Worker واحد (0.1 CPU) + خيوط كافية: تنزيلات + طابور الاستخراج + /health دون تجويع.
# --worker-tmp-dir /dev/shm: يمنع تجمد heartbeat على أقراص الحاويات البطيئة.
exec gunicorn -b 0.0.0.0:${PORT:-10000} \
  -w ${WORKERS:-1} \
  --threads ${THREADS:-24} \
  --worker-tmp-dir /dev/shm \
  --timeout 120 --graceful-timeout 30 --keep-alive 10 \
  app:app
