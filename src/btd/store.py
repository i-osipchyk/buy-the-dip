"""Where runs keep their data (ARCHITECTURE §10): JSON documents and bar snapshots under
``<env>/...`` keys, in S3 on Lambda or in a local directory (tests, local runs)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .data.bars import Snapshot


class Store(Protocol):
    def get_json(self, key: str) -> dict[str, Any] | None: ...

    def put_json(self, key: str, doc: dict[str, Any]) -> None: ...

    def get_bars(self, key: str) -> Snapshot | None: ...

    def put_bars(self, key: str, snapshot: Snapshot) -> None: ...


def _to_parquet(snapshot: Snapshot) -> bytes:
    frame = pd.concat([b.assign(ticker=t) for t, b in snapshot.items()], ignore_index=True)
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    return buf.getvalue()


def _from_parquet(data: bytes) -> Snapshot:
    frame = pd.read_parquet(io.BytesIO(data))
    return {str(t): g.drop(columns="ticker").reset_index(drop=True)
            for t, g in frame.groupby("ticker")}


class DirStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def get_json(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        return json.loads(path.read_text()) if path.exists() else None

    def put_json(self, key: str, doc: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1, default=str))

    def get_bars(self, key: str) -> Snapshot | None:
        path = self._path(key)
        return _from_parquet(path.read_bytes()) if path.exists() else None

    def put_bars(self, key: str, snapshot: Snapshot) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_to_parquet(snapshot))


class S3Store:
    """The platform data bucket: versioned, append-only (the role has no DeleteObject)."""

    def __init__(self, client: Any, bucket: str) -> None:
        self.client, self.bucket = client, bucket

    def _get(self, key: str) -> bytes | None:
        try:
            res = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey:
            return None
        return bytes(res["Body"].read())

    def get_json(self, key: str) -> dict[str, Any] | None:
        data = self._get(key)
        return json.loads(data) if data is not None else None

    def put_json(self, key: str, doc: dict[str, Any]) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, ContentType="application/json",
                               Body=json.dumps(doc, indent=1, default=str).encode())

    def get_bars(self, key: str) -> Snapshot | None:
        data = self._get(key)
        return _from_parquet(data) if data is not None else None

    def put_bars(self, key: str, snapshot: Snapshot) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=_to_parquet(snapshot))
