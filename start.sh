#!/bin/sh
set -e

# تحديث yt-dlp عند كل تشغيل (يوتيوب يغير أشياء باستمرار)
if [ "${AUTO_UPDATE:-1}" = "1" ]; then
  pip install -q -U "yt-dlp[default]" || true
fi

# سيرفر توليد PO Token (يقلل حجب IP السيرفرات)
if [ "${ENABLE_POT:-1}" = "1" ]; then
  NODE_OPTIONS="--max-old-space-size=160" node /opt/bgutil/server/build/main.js &
fi

exec gunicorn -b 0.0.0.0:${PORT:-10000} -w 1 --threads 4 --timeout 180 app:app
