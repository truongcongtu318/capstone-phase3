FROM docker.io/grafana/grafana:13.0.1@sha256:0f86bada30d65ef9d0183b90c1e2682ac92d53d95da8bed322b984ea78a4a73a

ARG GRAFANA_PLUGIN_VERSION=2.34.0
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
    && chown -R root:0 "${GF_PATHS_PLUGINS}" \
    && chmod -R a-w "${GF_PATHS_PLUGINS}"

USER 472
