FROM --platform=$BUILDPLATFORM docker.io/library/golang:1.26.5-bookworm@sha256:1ecb7edf62a0408027bd5729dfd6b1b8766e578e8df93995b225dfd0944eb651 AS grafana-builder

ARG TARGETOS
ARG TARGETARCH
ARG GRAFANA_SOURCE_COMMIT=5d189285069d02af604bfaeedb21a0b6ec4c4d0a
ARG GRAFANA_BUILD_NUMBER=30056490933

WORKDIR /src
RUN git init \
    && git remote add origin https://github.com/grafana/grafana.git \
    && git fetch --depth 1 origin "${GRAFANA_SOURCE_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${GRAFANA_SOURCE_COMMIT}"
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go get github.com/getkin/kin-openapi@v0.144.0 \
    && CGO_ENABLED=0 make build-go \
      OS="${TARGETOS}" \
      ARCH="${TARGETARCH}" \
      GO_BUILD_TAGS=oss \
      WIRE_TAGS=oss \
      COMMIT_SHA="${GRAFANA_SOURCE_COMMIT}" \
      BUILD_BRANCH=main \
      BUILD_NUMBER="${GRAFANA_BUILD_NUMBER}"

FROM docker.io/grafana/grafana:nightly-ubuntu-slim@sha256:7dcef0c66bc3692de69155ed9e229fee733c85e520207dcda26e1f52479dcb30

ARG GRAFANA_PLUGIN_VERSION=2.34.0
ARG TARGETARCH
ENV GF_PATHS_PLUGINS=/opt/grafana/plugins

USER root

RUN install -d -o 472 -g 0 -m 0755 "${GF_PATHS_PLUGINS}" \
    && grafana cli --pluginsDir "${GF_PATHS_PLUGINS}" plugins install \
      grafana-opensearch-datasource "${GRAFANA_PLUGIN_VERSION}" \
    && test -f "${GF_PATHS_PLUGINS}/grafana-opensearch-datasource/plugin.json" \
    && grep -Fq '"id": "grafana-opensearch-datasource"' \
      "${GF_PATHS_PLUGINS}/grafana-opensearch-datasource/plugin.json" \
    && grep -Fq "\"version\": \"${GRAFANA_PLUGIN_VERSION}\"" \
      "${GF_PATHS_PLUGINS}/grafana-opensearch-datasource/plugin.json" \
    && test -f \
      "${GF_PATHS_PLUGINS}/grafana-opensearch-datasource/MANIFEST.txt" \
    && test -x \
      "${GF_PATHS_PLUGINS}/grafana-opensearch-datasource/gpx_opensearch-datasource_linux_${TARGETARCH}"

COPY --from=grafana-builder \
    "/src/bin/linux/${TARGETARCH}/grafana" \
    "/usr/share/grafana/bin/grafana"

RUN test -x "/usr/share/grafana/bin/grafana" \
    && chown root:0 "/usr/share/grafana/bin/grafana" \
    && chmod a-w "/usr/share/grafana/bin/grafana" \
    && chown -R root:0 "${GF_PATHS_PLUGINS}" \
    && chmod -R a-w "${GF_PATHS_PLUGINS}"

USER 472
