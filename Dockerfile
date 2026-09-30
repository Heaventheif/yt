# syntax=docker/dockerfile:1
# ---- 1) اعتماديات Python في venv (بدون git/npm في الصورة النهائية) ----
FROM python:3.12-slim AS pybuild
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && pip show bgutil-ytdlp-pot-provider | awk '/^Version:/{print $2}' > /opt/bgutil.ver

# ---- 2) بناء سيرفر PO Token ثم حذف devDependencies والمصدر ----
FROM node:22-slim AS nodebuild
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=pybuild /opt/bgutil.ver /tmp/bgutil.ver
RUN VER=$(cat /tmp/bgutil.ver) \
 && ( git clone --depth 1 --branch "$VER" https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
   || git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil ) \
 && cd /opt/bgutil/server && npm ci --no-audit --no-fund && npx tsc \
 && npm prune --omit=dev --no-audit --no-fund \
 && rm -rf /opt/bgutil/.git /opt/bgutil/server/src /root/.npm

# ---- 3) الصورة النهائية: python:slim + ملف node فقط ----
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
COPY --from=nodebuild /opt/bgutil/server /opt/bgutil/server
COPY --from=pybuild /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    NODE_OPTIONS=--max-old-space-size=128

WORKDIR /app
COPY *.py start.sh ./
RUN chmod +x start.sh
USER app
CMD ["./start.sh"]
