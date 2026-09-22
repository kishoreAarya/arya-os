"""Local disk storage — the default backend, no external deps."""
import asyncio
from pathlib import Path

from app.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_path: str, public_base_url: str | None = None):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url

    def _resolve(self, key: str) -> Path:
        if not key or not isinstance(key, str):
            raise ValueError("Storage key must be a non-empty string")
        if "\0" in key:
            raise ValueError(f"Invalid key containing null byte: {key}")

        storage_root = self.base_path.resolve()
        normalized_key = key.replace("\\", "/")

        if normalized_key.startswith("/"):
            target = Path(normalized_key).resolve()
            if storage_root not in target.parents and target != storage_root:
                raise ValueError(f"Refusing to access outside storage root: {key}")
            return target

        clean_key = normalized_key.lstrip("/")
        path = (self.base_path / clean_key).resolve()
        if storage_root not in path.parents and path != storage_root:
            raise ValueError(f"Refusing to access outside storage root: {key}")
        return path

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._resolve(key)
        storage_root = self.base_path.resolve()
        if path == storage_root:
            raise ValueError("Cannot upload to storage root directory itself")
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return str(path.relative_to(self.base_path))

    async def download(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(f"Storage asset not found or not a regular file: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        try:
            path = self._resolve(key)
            if path.is_file():
                await asyncio.to_thread(path.unlink)
        except (ValueError, FileNotFoundError):
            pass

    async def exists(self, key: str) -> bool:
        try:
            path = self._resolve(key)
            return path.is_file()
        except (ValueError, OSError):
            return False

    def get_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"
        return str(self._resolve(key))
