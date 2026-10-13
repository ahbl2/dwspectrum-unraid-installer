FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
ARG DW_URL
ARG DW_SHA256
RUN test -n "$DW_URL" && test -n "$DW_SHA256" \
 && apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && mkdir -p /tmp/dw && cd /tmp/dw \
 && curl -fL --retry 3 "$DW_URL" -o download.zip \
 && echo "$DW_SHA256  download.zip" | sha256sum -c - \
 && unzip -q download.zip \
 && deb="$(find . -maxdepth 2 -name '*.deb' -type f -print -quit)" \
 && test -n "$deb" && apt-get install -y "./${deb#./}" \
 && echo 'currentOsVariantOverride=docker' >> /opt/digitalwatchdog/mediaserver/etc/mediaserver.conf \
 && echo 'ignoreRootTool=true' >> /opt/digitalwatchdog/mediaserver/etc/mediaserver.conf \
 && setcap -r /opt/digitalwatchdog/mediaserver/bin/mediaserver \
 && apt-get clean && rm -rf /tmp/dw /var/lib/apt/lists/*
# Move packaged mutable defaults into immutable seed locations and create links at build time.
RUN set -eux; \
 mkdir -p /opt/dw-seed /home/digitalwatchdog/.config; \
 mv /opt/digitalwatchdog/mediaserver/etc /opt/dw-seed/etc; \
 mv /opt/digitalwatchdog/mediaserver/var /opt/dw-seed/var; \
 ln -s /dwdata/config/etc /opt/digitalwatchdog/mediaserver/etc; \
 ln -s /dwdata/config/var /opt/digitalwatchdog/mediaserver/var; \
 ln -s /dwdata/config/ini /home/digitalwatchdog/.config/nx_ini
COPY docker-entrypoint.sh /usr/local/bin/dw-entrypoint
RUN chmod 755 /usr/local/bin/dw-entrypoint
EXPOSE 7001
ENTRYPOINT ["/usr/local/bin/dw-entrypoint"]
