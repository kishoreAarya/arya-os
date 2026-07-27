"""Local disk storage — the default backend, no external deps."""
import asyncio
from pathlib import Path

from app.storage.base import StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_path: str, public_base_url: str | None = None):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url

    def _resolve(self, key: str) -> Path:
        path = (self.base_path / key).resolve()
        if self.base_path.resolve() not in path.parents and path != self.base_path.resolve():
            raise ValueError(f"Refusing to write outside storage root: {key}")
        return path

    async def upload(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return str(path.relative_to(self.base_path))

    async def download(self, key: str) -> bytes:
        path = self._resolve(key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def get_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"
        return str(self._resolve(key))
