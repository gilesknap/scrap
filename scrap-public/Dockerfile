# scrap-public: the public site of scrap's public pages (nginx) and its internal
# upload receiver (receiver.py, stdlib only). One image, two commands:
#   scrap-public web       nginx on :8080, serving /site/www read only
#   scrap-public receive   the receiver on :8081, writing /site
# Runs as uid 10001 with a read-only root filesystem: mount /site (shared, writable
# by the receiver) and /tmp (each container its own).
FROM python:3.13-slim-trixie

RUN apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nginx \
    && apt-get dist-clean \
    && rm -rf /etc/nginx/sites-enabled /etc/nginx/conf.d /var/www/html

RUN useradd --uid 10001 --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin scrap-public \
    && mkdir -p /site/www && chown -R 10001:10001 /site

COPY nginx.conf.template /etc/scrap-public/nginx.conf.template
COPY receiver.py /usr/local/lib/scrap-public/receiver.py
COPY --chmod=755 entrypoint.sh /usr/local/bin/scrap-public

ENV RECEIVER_SITE=/site \
    RECEIVER_LISTEN=tcp:0.0.0.0:8081 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
VOLUME /site
EXPOSE 8080 8081
USER 10001:10001
WORKDIR /tmp

ENTRYPOINT ["scrap-public"]
CMD ["web"]
