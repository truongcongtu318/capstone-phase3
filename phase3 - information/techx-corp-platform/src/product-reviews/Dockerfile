# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0


FROM docker.io/library/python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322 AS build-venv

RUN apk update && \
    apk add gcc g++ linux-headers

COPY ./src/product-reviews/requirements.txt requirements.txt

RUN python -m venv venv && \
    venv/bin/pip install --no-cache-dir -r requirements.txt

RUN venv/bin/opentelemetry-bootstrap -a install

FROM docker.io/library/python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322

RUN apk update && \
    apk upgrade --no-cache libcrypto3 libssl3

COPY --from=build-venv /venv/ /venv/
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY ./src/product-reviews/demo_pb2_grpc.py demo_pb2_grpc.py
COPY ./src/product-reviews/demo_pb2.py demo_pb2.py
COPY ./src/product-reviews/product_reviews_server.py product_reviews_server.py
COPY ./src/product-reviews/database.py database.py
COPY ./src/product-reviews/metrics.py metrics.py
COPY ./src/product-reviews/guardrails guardrails
# Schema migration tooling. NOT part of the entrypoint — it only runs when invoked
# explicitly (a one-off Job overriding the command). Shipped in the image because
# RDS is private and reachable only from inside the VPC, so the migration has to be
# run from a pod; adds no credential exposure the pod does not already have.
COPY ./src/product-reviews/db_migration_worker.py db_migration_worker.py
COPY ./src/product-reviews/migration.sql migration.sql
RUN addgroup -S -g 65532 nonroot \
    && adduser -S -u 65532 -G nonroot nonroot \
    && chown -R 65532:65532 /app
USER 65532:65532


EXPOSE ${PRODUCT_REVIEWS_PORT}
ENTRYPOINT [ "/venv/bin/opentelemetry-instrument", "/venv/bin/python", "product_reviews_server.py" ]
