# Repository-root context; Dockerfile.dockerignore excludes local state and secrets.
ARG UI_APP=patient-frontend
FROM node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
ARG UI_APP
WORKDIR /app

RUN case "$UI_APP" in patient-frontend|doctor-frontend) ;; *) echo 'UI_APP must be patient-frontend or doctor-frontend' >&2; exit 1 ;; esac
COPY frontend/${UI_APP}/package.json frontend/${UI_APP}/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/${UI_APP}/index.html frontend/${UI_APP}/tsconfig.json frontend/${UI_APP}/tsconfig.app.json frontend/${UI_APP}/tsconfig.node.json frontend/${UI_APP}/vite.config.ts ./
COPY frontend/${UI_APP}/src/ ./src/
COPY frontend/${UI_APP}/public/ ./public/
RUN VITE_SKINAI_API=true npm run build

FROM nginx/nginx-unprivileged:stable-alpine@sha256:6b0610b60dff09248d642643a29393543a92eb355b00bbd1d12c7af562ef94c4 AS runtime
ENV SKINAI_PROXY_TIMEOUT=60s
COPY --from=build --chown=101:101 /app/dist/ /usr/share/nginx/html/
COPY ci/release/frontend/nginx.conf.template /etc/nginx/skinai.conf.template
COPY --chmod=0555 ci/release/frontend/entrypoint.sh /usr/local/bin/skinai-ui-entrypoint.sh
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["/usr/local/bin/skinai-ui-entrypoint.sh"]
CMD ["nginx", "-c", "/tmp/skinai-nginx.conf", "-g", "daemon off;"]
