FROM python:3.12-slim

ARG APT_MIRROR=https://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|https://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|http://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|https://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|https://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|http://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|https://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            /etc/apt/sources.list; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY app /app/app
COPY config.py /app/config.py

RUN mkdir -p /app/uploads \
    && useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
