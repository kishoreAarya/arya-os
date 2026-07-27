"""
S3-compatible storage — covers both AWS S3 and Cloudflare R2, since R2
speaks the S3 API. Pointing STORAGE_ENDPOINT_URL at R2's endpoint is
the entire difference; boto3 doesn't know or care which it's talking to.
"""
import asyncio

from app.storage.base import StorageProvider


class S3StorageProvider(StorageProvider):
    def __init__(
        self,
        bucket: str,
        access_key: str | None,
        secret_key: str | None,
        region: str | None = None,
        endpoint_url: str | None = None,  # set this for R2 / non-AWS S3-compatible
        public_base_url: str | None = None,
    ):
        import boto3  # imported lazily so `boto3` is only required when this backend is selected

        self.bucket = bucket
        self.public_base_url = public_base_url
        self._client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            endpoint_url=endpoint_url,
        )

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        kwargs = {"Bucket": self.bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        await asyncio.to_thread(self._client.put_object, **kwargs)
        return key

    async def download(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001 — boto3 raises ClientError for 404s
            return False

    def get_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600
        )
