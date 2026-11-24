# syntax=docker/dockerfile:1

# MLflow with what its official image lacks: the PostgreSQL driver (backend store) and boto3 (artifacts in S3).
ARG MLFLOW_VERSION=3.18.0
FROM ghcr.io/mlflow/mlflow:v${MLFLOW_VERSION}

RUN pip install --no-cache-dir psycopg2-binary boto3 \
    && useradd --create-home --uid 1000 mlflow
COPY init.py /opt/init.py
USER mlflow
EXPOSE 5000
