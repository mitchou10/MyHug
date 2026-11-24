from urllib.parse import quote

import aioboto3
from botocore.exceptions import ClientError

from app.storage.base import ObjectInfo, PartInfo, StoredObject


class S3Store:
    """An S3-compatible storage (RustFS, MinIO, AWS...), spoken to without blocking the event loop."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        public_endpoint_url: str = "",
    ) -> None:
        self._bucket = bucket
        self._session = aioboto3.Session()
        self._client_args = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region,
        }
        # The browser may not reach the storage at the address the API does (inside Docker, `rustfs:9000`): the signed
        # addresses are made for the one it reaches.
        self._public_args = {**self._client_args, "endpoint_url": public_endpoint_url or endpoint_url}
        self._bucket_ready = False

    def _client(self, *, public: bool = False):
        return self._session.client("s3", **(self._public_args if public else self._client_args))

    async def _ensure_bucket(self, s3) -> None:
        # Lazy: no network call at import time. A real connectivity or permission problem still surfaces on the
        # call that follows.
        if self._bucket_ready:
            return
        try:
            await s3.create_bucket(Bucket=self._bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
        self._bucket_ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> StoredObject | None:
        async with self._client() as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
                    return None
                raise
            async with response["Body"] as body:
                return StoredObject(data=await body.read(), content_type=response["ContentType"])

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def head(self, key: str) -> ObjectInfo | None:
        async with self._client() as s3:
            try:
                response = await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound", "NoSuchBucket"):
                    return None
                raise
            return ObjectInfo(size=response["ContentLength"], content_type=response.get("ContentType", ""))

    async def create_multipart(self, key: str, content_type: str) -> str:
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            response = await s3.create_multipart_upload(Bucket=self._bucket, Key=key, ContentType=content_type)
            return response["UploadId"]

    async def presign_part(self, key: str, upload_id: str, number: int, expires_in: int) -> str:
        # Signing is done here, without a call to the storage: only the address in it matters to the browser.
        async with self._client(public=True) as s3:
            return await s3.generate_presigned_url(
                "upload_part",
                Params={"Bucket": self._bucket, "Key": key, "UploadId": upload_id, "PartNumber": number},
                ExpiresIn=expires_in,
            )

    async def list_parts(self, key: str, upload_id: str) -> list[PartInfo]:
        parts: list[PartInfo] = []
        marker = 0
        async with self._client() as s3:
            while True:
                response = await s3.list_parts(
                    Bucket=self._bucket, Key=key, UploadId=upload_id, PartNumberMarker=marker
                )
                parts += [
                    PartInfo(number=p["PartNumber"], size=p["Size"], etag=p["ETag"]) for p in response.get("Parts", [])
                ]
                if not response.get("IsTruncated"):
                    return parts
                marker = response["NextPartNumberMarker"]

    async def complete_multipart(self, key: str, upload_id: str, parts: list[PartInfo]) -> None:
        async with self._client() as s3:
            await s3.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={
                    "Parts": [{"PartNumber": p.number, "ETag": p.etag} for p in sorted(parts, key=lambda p: p.number)]
                },
            )

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        async with self._client() as s3:
            try:
                await s3.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
            except ClientError as error:
                if error.response["Error"]["Code"] != "NoSuchUpload":
                    raise

    async def presign_get(self, key: str, expires_in: int, filename: str | None = None) -> str:
        params = {"Bucket": self._bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        async with self._client(public=True) as s3:
            return await s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
