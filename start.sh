#!/bin/sh
set -e

# تحديث yt-dlp عند التشغيل (اختياري، يبطئ الإقلاع على الخطة المجانية) — الأفضل إعادة النشر
if [ "${AUTO_UPDATE:-0}" = "1" ]; then
  pip install -q -U "yt-dlp[default]" || true
fi

# سيرفر توليد PO Token (يقلل حجب IP السيرفرات)
if [ "${ENABLE_POT:-1}" = "1" ]; then
  node /opt/bgutil/server/build/main.js &
fi

exec gunicorn -b 0.0.0.0:${PORT:-10000} -w 1 --threads ${THREADS:-16} \
  --timeout 120 --graceful-timeout 30 --keep-alive 10 app:app
