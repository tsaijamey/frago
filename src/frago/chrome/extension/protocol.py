"""JSON-RPC 2.0 message types used between frago and the browser extension.

Wire format (stdio, Chrome native messaging):
    <4-byte native-endian length><UTF-8 JSON payload>

Wire format (unix socket, CLI ↔ daemon):
    <4-byte little-endian length><UTF-8 JSON payload>

Chrome's native messaging uses native byte order for the length prefix; on
little-endian hosts this is identical to the uds framing. We target Linux
first, so both transports use ``<I`` (little-endian uint32). Update if
targeting big-endian hosts.
"""
from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


RPC_ERROR_CODES = {
    "PARSE_ERROR":            -32700,
    "INVALID_REQUEST":        -32600,
    "METHOD_NOT_FOUND":       -32601,
    "INVALID_PARAMS":         -32602,
    "INTERNAL_ERROR":         -32603,
    "NO_GROUP":               -32001,
    "NO_TAB":                 -32002,
    "EXTENSION_NOT_READY":    -32003,
    "COMMAND_FAILED":         -32004,
    "TIMEOUT":                -32005,
}


@dataclass
class RpcError:
    code: int
    message: str
    data: Optional[dict] = None


@dataclass
class RpcRequest:
    method: str
    params: dict = field(default_factory=dict)
    id: Optional[str] = None
    jsonrpc: Literal["2.0"] = "2.0"

    def to_json(self) -> dict:
        return {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }


@dataclass
class RpcResponse:
    id: Optional[str]
    result: Any = None
    error: Optional[RpcError] = None
    jsonrpc: Literal["2.0"] = "2.0"

    def to_json(self) -> dict:
        out: dict = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            out["error"] = asdict(self.error)
        else:
            out["result"] = self.result
        return out


def encode_frame(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def read_frame_sync(stream) -> Optional[dict]:
    """Blocking read of one frame from a binary stream; None on EOF."""
    header = stream.read(4)
    if not header or len(header) < 4:
        return None
    (length,) = struct.unpack("<I", header)
    body = stream.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode("utf-8"))


async def read_frame_async(reader) -> Optional[dict]:
    """Async read of one frame from an asyncio StreamReader; None on EOF."""
    try:
        header = await reader.readexactly(4)
    except Exception:
        return None
    (length,) = struct.unpack("<I", header)
    try:
        body = await reader.readexactly(length)
    except Exception:
        return None
    return json.loads(body.decode("utf-8"))
