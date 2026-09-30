FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip git ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# سيرفر PO Token بنفس إصدار الـ plugin
RUN VER=$(pip show bgutil-ytdlp-pot-provider | awk '/^Version:/{print $2}') \
 && ( git clone --depth 1 --branch "$VER" https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
   || git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil ) \
 && cd /opt/bgutil/server && npm ci && npx tsc

COPY *.py start.sh ./
RUN chmod +x start.sh

ENV NODE_OPTIONS=--max-old-space-size=96 \
    MALLOC_ARENA_MAX=2 \
    PYTHONMALLOC=malloc

CMD ["./start.sh"]
