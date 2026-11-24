"""Before MLflow starts: its database and the bucket of its artifacts exist.

Both are made if they are missing and left alone if they are there, so it can run at every `docker compose up`, on a
database that already exists (an init script of PostgreSQL only runs on an empty volume) and on a storage that is new.
"""

import os
import sys
import time
from urllib.parse import urlsplit

import boto3
import psycopg2
from botocore.exceptions import ClientError

BACKEND_STORE = os.environ["MLFLOW_BACKEND_STORE_URI"]  # postgresql+psycopg2://user:password@host:5432/mlflow
ARTIFACTS = os.environ["MLFLOW_ARTIFACTS_DESTINATION"]  # s3://bucket/prefix


def database() -> None:
    url = urlsplit(BACKEND_STORE)
    name = url.path.lstrip("/")
    for attempt in range(30):
        try:
            # The `postgres` database always exists: it is where a database is made from.
            connection = psycopg2.connect(
                host=url.hostname, port=url.port or 5432, user=url.username, password=url.password, dbname="postgres"
            )
            break
        except psycopg2.OperationalError:
            if attempt == 29:
                raise
            time.sleep(2)
    connection.autocommit = True
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cursor.fetchone() is None:
            cursor.execute(f'CREATE DATABASE "{name}"')
            print(f"database {name} created")
        else:
            print(f"database {name} is there")
    finally:
        connection.close()


def bucket() -> None:
    name = urlsplit(ARTIFACTS).netloc
    s3 = boto3.client("s3", endpoint_url=os.environ.get("MLFLOW_S3_ENDPOINT_URL"))
    try:
        s3.head_bucket(Bucket=name)
        print(f"bucket {name} is there")
    except ClientError:
        s3.create_bucket(Bucket=name)
        print(f"bucket {name} created")


if __name__ == "__main__":
    database()
    bucket()
    sys.exit(0)
