import socket
from collections.abc import Iterator

import aioboto3
import pytest
from moto.server import ThreadedMotoServer

from app.storage import ObjectNotFound, S3Store


@pytest.fixture(scope="module")
def s3_url() -> Iterator[str]:
    """A real S3 API over HTTP, in memory: aioboto3 does network calls, so it cannot be patched like boto3."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


def make_store(url: str, bucket: str) -> S3Store:
    return S3Store(bucket=bucket, endpoint_url=url, access_key_id="test", secret_access_key="test", region="us-east-1")


async def test_put_creates_the_bucket_and_get_gives_the_object_back(s3_url: str) -> None:
    store = make_store(s3_url, "photos")
    await store.put("a/b", b"data", "image/png")
    stored = await store.get("a/b")
    assert stored is not None and (stored.data, stored.content_type) == (b"data", "image/png")


async def test_put_works_when_the_bucket_already_exists(s3_url: str) -> None:
    await make_store(s3_url, "shared").put("k", b"x", "image/png")
    await make_store(s3_url, "shared").put("k2", b"y", "image/png")  # a second store: the bucket is already there


async def test_a_missing_object_is_none(s3_url: str) -> None:
    store = make_store(s3_url, "photos2")
    await store.put("k", b"x", "image/png")
    assert await store.get("nope") is None


async def test_a_missing_bucket_is_none(s3_url: str) -> None:
    assert await make_store(s3_url, "ghost").get("k") is None


async def test_delete(s3_url: str) -> None:
    store = make_store(s3_url, "photos3")
    await store.put("k", b"x", "image/png")
    await store.delete("k")
    assert await store.get("k") is None


async def test_another_error_is_not_hidden(s3_url: str) -> None:
    # A bucket name S3 refuses: the error must come out, not be taken for "already exists".
    with pytest.raises(Exception):  # noqa: B017
        await make_store(s3_url, "X").put("k", b"x", "image/png")


def test_the_session_is_aioboto3() -> None:
    assert aioboto3.Session  # the dependency the store is built on


# ---- a large file goes in parts, straight from the browser


MIB = 1024 * 1024


async def send(url: str, data: bytes) -> str:
    """What the browser does with a signed address: sends one part. Returns the fingerprint the storage gave it."""
    import httpx2

    async with httpx2.AsyncClient() as client:
        response = await client.put(url, content=data)
    assert response.status_code == 200, response.text
    return response.headers["etag"]


async def test_a_file_is_uploaded_in_parts_to_signed_addresses_and_put_together(s3_url: str) -> None:
    store = make_store(s3_url, "parts")
    upload_id = await store.create_multipart("big/file", "text/csv")
    first, second = b"a" * (5 * MIB), b"tail"
    await send(await store.presign_part("big/file", upload_id, 1, 600), first)
    await send(await store.presign_part("big/file", upload_id, 2, 600), second)

    parts = await store.list_parts("big/file", upload_id)
    assert [(p.number, p.size) for p in parts] == [(1, 5 * MIB), (2, 4)]
    assert await store.head("big/file") is None  # nothing exists until the parts are put together
    await store.complete_multipart("big/file", upload_id, parts)

    info = await store.head("big/file")
    assert info is not None and (info.size, info.content_type) == (5 * MIB + 4, "text/csv")
    stored = await store.get("big/file")
    assert stored is not None and stored.data == first + second


async def test_the_parts_that_arrived_are_known_when_an_upload_is_resumed(s3_url: str) -> None:
    store = make_store(s3_url, "resume")
    upload_id = await store.create_multipart("k", "application/octet-stream")
    await send(await store.presign_part("k", upload_id, 2, 600), b"x" * (5 * MIB))  # the second one arrived first
    assert [p.number for p in await store.list_parts("k", upload_id)] == [2]


async def test_the_signed_address_is_the_one_the_browser_reaches(s3_url: str) -> None:
    store = S3Store(
        bucket="public",
        endpoint_url=s3_url,
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        public_endpoint_url="https://files.example.com",
    )
    upload_id = await store.create_multipart(
        "k", "text/plain"
    )  # the API itself speaks to the storage at its own address
    assert (await store.presign_part("k", upload_id, 1, 600)).startswith("https://files.example.com/public/k?")
    assert (await store.presign_get("k", 600)).startswith("https://files.example.com/public/k?")
    assert (await store.presign_get("k", 600, internal=True)).startswith(f"{s3_url}/public/k?")  # for the worker


async def test_the_signed_addresses_use_signature_version_4(s3_url: str) -> None:
    """With the old version 2 (boto's default for these addresses) RustFS answers SignatureDoesNotMatch."""
    store = make_store(s3_url, "signed")
    upload_id = await store.create_multipart("k", "text/plain")
    for url in (await store.presign_part("k", upload_id, 1, 600), await store.presign_get("k", 600)):
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url and "X-Amz-Signature=" in url


async def test_giving_up_an_upload_frees_it_and_can_be_done_twice(s3_url: str) -> None:
    store = make_store(s3_url, "abort")
    upload_id = await store.create_multipart("k", "text/plain")
    await send(await store.presign_part("k", upload_id, 1, 600), b"x")
    await store.abort_multipart("k", upload_id)
    await store.abort_multipart("k", upload_id)  # already gone: nothing to say
    assert await store.head("k") is None


async def test_an_object_is_downloaded_from_a_signed_address(s3_url: str) -> None:
    import httpx2

    store = make_store(s3_url, "download")
    await store.put("a/b.csv", b"n\n1\n", "text/csv")
    url = await store.presign_get("a/b.csv", 600, filename="données.csv")
    async with httpx2.AsyncClient() as client:
        response = await client.get(url)
    assert response.status_code == 200 and response.content == b"n\n1\n"
    assert "UTF-8''donn%C3%A9es.csv" in response.headers["content-disposition"]


async def test_head_says_nothing_of_an_object_that_is_not_there(s3_url: str) -> None:
    store = make_store(s3_url, "heads")
    await store.put("k", b"x", "text/plain")
    assert await store.head("nope") is None
    assert await make_store(s3_url, "ghost-bucket").head("k") is None


async def test_a_range_of_an_object_is_read_without_the_rest(s3_url: str) -> None:
    store = make_store(s3_url, "ranges")
    await store.put("k", b"0123456789", "text/plain")
    assert await store.get_range("k", 2, 4) == b"2345"
    assert await store.get_range("k", 8, 100) == b"89"  # up to the end
    assert await store.get_range("k", 50, 10) == b""  # past the end
    with pytest.raises(ObjectNotFound):
        await store.get_range("missing", 0, 1)


async def test_the_address_of_a_part_for_the_worker_is_the_one_of_the_storage_itself(s3_url: str) -> None:
    store = S3Store(
        bucket="internal",
        endpoint_url=s3_url,
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        public_endpoint_url="https://files.example.com",
    )
    upload_id = await store.create_multipart("k", "text/plain")
    assert (await store.presign_part("k", upload_id, 1, 600)).startswith("https://files.example.com/internal/k?")
    assert (await store.presign_part("k", upload_id, 1, 600, internal=True)).startswith(f"{s3_url}/internal/k?")
