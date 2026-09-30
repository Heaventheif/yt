#!/bin/sh
set -e

if [ "${AUTO_UPDATE:-0}" = "1" ]; then
  pip install -q -U "yt-dlp[default]" || true
fi

if [ "${ENABLE_POT:-1}" = "1" ]; then
  node /opt/bgutil/server/build/main.js &
fi

# عامل واحد مناسب للخطة الصغيرة؛ إعادة التدوير تمنع تراكم الذاكرة بعد طلبات كثيرة.
exec gunicorn -b 0.0.0.0:${PORT:-10000} \
  -w ${WORKERS:-1} \
  --threads ${THREADS:-8} \
  --max-requests ${MAX_REQUESTS:-300} \
  --max-requests-jitter ${MAX_REQUESTS_JITTER:-60} \
  --timeout 120 --graceful-timeout 30 --keep-alive 10 \
  app:app
