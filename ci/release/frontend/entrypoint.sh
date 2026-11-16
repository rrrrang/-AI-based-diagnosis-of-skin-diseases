#!/bin/sh
set -eu

# Substitute only the supported setting, preserving nginx's own $variables.
# Keep generated configuration on tmpfs when the root filesystem is read-only.
if ! printf '%s\n' "$SKINAI_PROXY_TIMEOUT" | grep -Eq '^[1-9][0-9]*(ms|s|m)?$'; then
    echo 'SKINAI_PROXY_TIMEOUT must be a positive duration, for example 60s' >&2
    exit 1
fi
umask 077
envsubst '${SKINAI_PROXY_TIMEOUT}' < /etc/nginx/skinai.conf.template > /tmp/skinai-nginx.conf
exec "$@"
