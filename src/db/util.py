from __future__ import annotations
import uuid

def new_uuid() -> str:
    return str(uuid.uuid4())

def uuid_to_bin(u: str) -> bytes:
    return uuid.UUID(u).bytes  # 与表的 BINARY(16) 对应

def bin_to_uuid(b: bytes) -> str:
    return str(uuid.UUID(bytes=b))