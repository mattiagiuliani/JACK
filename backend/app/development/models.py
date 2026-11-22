"""Bounded UTF-8 artifacts and portable paths; input text is never an instruction."""

import hashlib
import json
import re
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.agents.research import ResearchModel, Text

MAX_FILE_BYTES = 262_144
MAX_BUNDLE_BYTES = 1_048_576


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class DevelopmentRequest(ResearchModel):
    plan_id: UUID
    task_ids: Annotated[tuple[Text, ...], Field(min_length=1, max_length=100)]
    actor: Text
    reason: Text
    target: Literal["static-prototype-v1"]

    @field_validator("task_ids")
    @classmethod
    def unique_tasks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate task id")
        return value


class SourceFile(ResearchModel):
    path: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[str, Field(max_length=MAX_FILE_BYTES)]

    @field_validator("path")
    @classmethod
    def portable(cls, value: str) -> str:
        for part in value.split("/"):
            if (
                len(part) > 80
                or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part)
                or part.endswith(".")
                or re.fullmatch(
                    r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])", part.split(".")[0]
                )
            ):
                raise ValueError("Unsafe or non-portable artifact path")
        return value

    @field_validator("content")
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        if "\x00" in value or "\r" in value:
            raise ValueError("Artifacts require normalized text without NUL or CR")
        if len(value.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Artifact exceeds byte limit")
        return value


class ManifestEntry(ResearchModel):
    path: str
    size: int
    sha256: str


class Bundle(ResearchModel):
    provider: Literal["static-prototype-v1"] = "static-prototype-v1"
    files: Annotated[tuple[SourceFile, ...], Field(min_length=1, max_length=100)]
    task_order: tuple[Text, ...]
    completion: Literal["prototype_requires_review"] = "prototype_requires_review"
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def bounds(self) -> Self:
        names = [f.path.casefold() for f in self.files]
        if len(names) != len(set(names)) or any(
            name == "manifest.json" or name.startswith("manifest.json/")
            for name in names
        ):
            raise ValueError("Duplicate or reserved manifest path")
        for name in names:
            parts = name.split("/")
            if any("/".join(parts[:index]) in names for index in range(1, len(parts))):
                raise ValueError("Artifact path collides with a parent file")
        if sum(len(f.content.encode("utf-8")) for f in self.files) > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle exceeds byte limit")
        return self

    def manifest(self) -> dict[str, object]:
        entries = [
            ManifestEntry(
                path=f.path,
                size=len(f.content.encode("utf-8")),
                sha256=digest(f.content.encode("utf-8")),
            ).model_dump()
            for f in sorted(self.files, key=lambda f: f.path)
        ]
        return {
            "schema_version": "102-v1",
            "provider": self.provider,
            "task_order": self.task_order,
            "completion": self.completion,
            "execution_authorized": False,
            "files": entries,
        }

    def fingerprint(self) -> str:
        return digest(canonical(self.manifest()))


class ExportRequest(ResearchModel):
    actor: Text
    reason: Text
