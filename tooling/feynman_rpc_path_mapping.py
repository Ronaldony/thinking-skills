#!/usr/bin/env python3
"""Map declared Codex RPC file paths between a Windows host and Linux mounts.

The Docker boundary already maps host sources to container destinations. The
Codex control/exec-server protocol has a second path namespace, carried in
selected JSON-RPC fields. This module handles only those declared fields and
only ``file:`` URIs or raw path values for a known method. It does not rewrite
arbitrary JSON strings or command arguments.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping
from urllib.parse import quote, unquote, urlsplit

try:
    from .feynman_path_mapping import CONTAINER_DESTINATIONS, PATH_KEYS, mounts_for_job
except ImportError:
    from feynman_path_mapping import CONTAINER_DESTINATIONS, PATH_KEYS, mounts_for_job


class RpcPathMappingError(ValueError):
    """A declared RPC path cannot be safely mapped."""


REQUEST_PATH_FIELDS: dict[str, frozenset[str]] = {
    "command/exec": frozenset({"cwd"}),
    "process/exec": frozenset({"cwd"}),
    "process/start": frozenset({"cwd"}),
    "environmentConfig/read": frozenset({"cwd"}),
    "fs/canonicalize": frozenset({"path"}),
    "fs/getMetadata": frozenset({"path"}),
    "fs/walk": frozenset({"path"}),
    "fs/readFile": frozenset({"path"}),
    "fs/writeFile": frozenset({"path"}),
    "resources/read": frozenset({"uri"}),
}
REQUEST_PATH_ARRAY_FIELDS = {
    "environmentConfig/read": frozenset({"configPaths", "requirementsPaths"}),
}
RESPONSE_PATH_FIELDS = frozenset({"cwd", "path", "uri"})


def _is_windows_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[0].isalpha() and value[2] in {"/", "\\"}


def _windows_key(path: PureWindowsPath) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _posix_key(path: PurePosixPath) -> tuple[str, ...]:
    return path.parts


def _file_uri_path(value: str) -> tuple[str, PureWindowsPath | PurePosixPath]:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "file" or parsed.netloc not in {"", "localhost"}:
        raise RpcPathMappingError("only local file URIs are supported")
    if parsed.query or parsed.fragment:
        raise RpcPathMappingError("file URI query and fragment components are unsupported")
    raw = unquote(parsed.path)
    if _is_windows_path(raw.lstrip("/")):
        return "windows", PureWindowsPath(raw.lstrip("/"))
    return "posix", PurePosixPath(raw)


def _file_uri(path: PureWindowsPath | PurePosixPath) -> str:
    if isinstance(path, PureWindowsPath):
        value = "/" + path.as_posix()
    else:
        value = path.as_posix()
    return "file://" + quote(value, safe="/:@-._~")


def _relative(parts: tuple[str, ...], root: tuple[str, ...]) -> tuple[str, ...] | None:
    if len(parts) < len(root) or parts[: len(root)] != root:
        return None
    return parts[len(root) :]


@dataclass(frozen=True)
class RpcPathMapper:
    """Validated host/container mount pairs in longest-root-first order."""

    mounts: tuple[tuple[PureWindowsPath | PurePosixPath, PurePosixPath], ...]

    @classmethod
    def from_mounts(cls, mounts: list[Mapping[str, str]]) -> "RpcPathMapper":
        pairs: list[tuple[PureWindowsPath | PurePosixPath, PurePosixPath]] = []
        for item in mounts:
            source = item.get("source")
            destination = item.get("destination")
            if not isinstance(source, str) or not isinstance(destination, str):
                raise RpcPathMappingError("mount source and destination must be strings")
            if _is_windows_path(source):
                host: PureWindowsPath | PurePosixPath = PureWindowsPath(source)
            else:
                host = PurePosixPath(source)
            container = PurePosixPath(destination)
            if not container.is_absolute() or ".." in container.parts:
                raise RpcPathMappingError("container mount destination is unsafe")
            pairs.append((host, container))
        if not pairs:
            raise RpcPathMappingError("at least one mount is required")
        pairs.sort(key=lambda pair: len(pair[0].parts), reverse=True)
        return cls(tuple(pairs))

    @classmethod
    def from_job(cls, job: Mapping[str, Any], profile: Mapping[str, Any]) -> "RpcPathMapper":
        mounts = mounts_for_job(job, profile)
        allowed = {CONTAINER_DESTINATIONS[key] for key in PATH_KEYS}
        selected = [item for item in mounts if item["destination"] in allowed]
        return cls.from_mounts(selected)

    def _host_to_container_path(self, path: str) -> PurePosixPath:
        if _is_windows_path(path):
            value: PureWindowsPath | PurePosixPath = PureWindowsPath(path)
            parts = _windows_key(value)
        else:
            value = PurePosixPath(path)
            parts = _posix_key(value)
        if not value.is_absolute() or ".." in value.parts:
            raise RpcPathMappingError("host path must be absolute and traversal-free")
        for host, container in self.mounts:
            host_parts = _windows_key(host) if isinstance(host, PureWindowsPath) else _posix_key(host)
            relative = _relative(parts, host_parts)
            if relative is not None:
                # Compare Windows components case-insensitively, but preserve
                # the caller's relative spelling for the Linux path.
                return container.joinpath(*value.parts[len(host.parts) :])
        raise RpcPathMappingError("host path is outside declared mounts")

    def _container_to_host_path(self, path: str) -> PureWindowsPath | PurePosixPath:
        value = PurePosixPath(path)
        if not value.is_absolute() or ".." in value.parts:
            raise RpcPathMappingError("container path must be absolute and traversal-free")
        for host, container in self.mounts:
            relative = _relative(_posix_key(value), _posix_key(container))
            if relative is not None:
                return host.joinpath(*relative)
        raise RpcPathMappingError("container path is outside declared mounts")

    def _declared_container_path(self, path: str) -> PurePosixPath:
        """Validate and retain a path already in the container namespace."""
        self._container_to_host_path(path)
        return PurePosixPath(path)

    def host_to_container(self, value: str) -> str:
        if value.startswith("file:"):
            kind, path = _file_uri_path(value)
            if kind == "windows":
                return _file_uri(self._host_to_container_path(path.as_posix()))
            return _file_uri(self._declared_container_path(path.as_posix()))
        if value.startswith("/"):
            # A raw POSIX absolute path is already in the remote/container
            # namespace.  Do not fall back to host-path parsing when it is
            # outside the declared mounts; that both mislabels the failure
            # and can reinterpret a remote path using host rules.
            return self._declared_container_path(value).as_posix()
        return self._host_to_container_path(value).as_posix()

    def container_to_host(self, value: str) -> str:
        if value.startswith("file:"):
            kind, path = _file_uri_path(value)
            if kind != "posix":
                raise RpcPathMappingError("container file URI must use POSIX paths")
            return _file_uri(self._container_to_host_path(path.as_posix()))
        return str(self._container_to_host_path(value))

    def map_request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        method = message.get("method")
        fields = REQUEST_PATH_FIELDS.get(method) if isinstance(method, str) else None
        if not fields:
            return dict(message)
        params = message.get("params")
        if not isinstance(params, Mapping):
            return dict(message)
        mapped = dict(message)
        mapped_params = dict(params)
        for field in fields:
            value = mapped_params.get(field)
            if isinstance(value, str) and (value.startswith("file:") or value.startswith("/") or _is_windows_path(value)):
                mapped_params[field] = self.host_to_container(value)
        for field in REQUEST_PATH_ARRAY_FIELDS.get(method, ()):
            if field not in mapped_params:
                continue
            values = mapped_params[field]
            if not isinstance(values, list):
                raise RpcPathMappingError("declared path array must be a list")
            mapped_values = []
            for item in values:
                if not isinstance(item, list) or not all(isinstance(x, str) for x in item):
                    raise RpcPathMappingError("config path groups must contain only paths")
                mapped_values.append([self.host_to_container(x) for x in item])
            mapped_params[field] = mapped_values
        mapped["params"] = mapped_params
        return mapped

    def map_response(self, message: Mapping[str, Any], *, request_method: str | None = None) -> dict[str, Any]:
        mapped = dict(message)
        fields = RESPONSE_PATH_FIELDS
        if request_method == "environment/info":
            # App Server documents this response's cwd as using the remote
            # environment's native syntax.  A Linux remote cwd (for example
            # its service default outside a candidate mount) is therefore
            # not a host path and must not be forced through the declared
            # Windows mount map.
            fields = RESPONSE_PATH_FIELDS - {"cwd"}
        for envelope in ("result", "error"):
            value = mapped.get(envelope)
            if isinstance(value, Mapping):
                mapped_value = dict(value)
                for field in fields:
                    item = mapped_value.get(field)
                    if isinstance(item, str) and (item.startswith("file:") or item.startswith("/")):
                        mapped_value[field] = self.container_to_host(item)
                mapped[envelope] = mapped_value
        return mapped


def map_json_line(mapper: RpcPathMapper, line: str, *, response: bool = False,
                  request_method: str | None = None) -> str:
    """Map one JSON-RPC line while preserving all non-path values."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RpcPathMappingError("RPC line is not valid JSON") from exc
    if not isinstance(message, Mapping):
        raise RpcPathMappingError("RPC message must be a JSON object")
    mapped = (mapper.map_response(message, request_method=request_method)
              if response else mapper.map_request(message))
    if mapped == message:
        return line.rstrip("\r\n")
    return json.dumps(mapped, ensure_ascii=False, separators=(",", ":"))
