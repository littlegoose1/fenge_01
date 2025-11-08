import uuid
from typing import Optional


def uuid4_bytes() -> bytes:
    return uuid.uuid4().bytes


def uuid_bytes_to_str(b: Optional[bytes]) -> Optional[str]:
    if b is None:
        return None
    return str(uuid.UUID(bytes=b))


def uuid_str_to_bytes(s: str) -> bytes:
    return uuid.UUID(s).bytes