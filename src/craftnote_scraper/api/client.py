import os
from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path
from typing import Final

import httpx

from craftnote_scraper.api.exceptions import (
    CraftnoteAPIError,
    CraftnoteAuthenticationError,
    CraftnoteNotFoundError,
    CraftnoteRateLimitError,
)
from craftnote_scraper.api.models import CompanyMember, Project, ProjectFile

DEFAULT_BASE_URL: Final[str] = "https://europe-west1-craftnote-live.cloudfunctions.net/api/v1"
DEFAULT_LIMIT: Final[int] = 100
DEFAULT_TIMEOUT_SECONDS: Final[int] = 30


class PaginationMode(StrEnum):
    OFFSET = "offset"
    CURSOR = "token"


def _load_secrets_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    env_vars: dict[str, str] = {}
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()
    return env_vars


def _get_config_value(key: str, secrets: dict[str, str], default: str | None = None) -> str | None:
    return os.environ.get(key) or secrets.get(key) or default


class CraftnoteClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        secrets_path: Path | None = None,
    ):
        secrets_file = secrets_path or Path("secrets.env")
        secrets = _load_secrets_env(secrets_file)

        resolved_api_key = api_key or _get_config_value("CRAFTNOTE_API_KEY", secrets)
        if not resolved_api_key:
            raise CraftnoteAuthenticationError("API key is required", status_code=None)
        self._api_key: str = resolved_api_key

        base = base_url or _get_config_value("CRAFTNOTE_URL", secrets, DEFAULT_BASE_URL)
        if base is None:
            base = DEFAULT_BASE_URL
        self._base_url: str = f"{base}/api/v1" if not base.endswith("/api/v1") else base

        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CraftnoteClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-CN-API-KEY": self._api_key},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise CraftnoteAPIError("Client not initialized. Use 'async with' context manager.")
        return self._client

    def _handle_response_errors(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise CraftnoteAuthenticationError(
                "Invalid or missing API key", status_code=response.status_code
            )
        if response.status_code == 404:
            raise CraftnoteNotFoundError("Resource not found", status_code=response.status_code)
        if response.status_code == 429:
            raise CraftnoteRateLimitError("Rate limit exceeded", status_code=response.status_code)
        if response.status_code >= 400:
            raise CraftnoteAPIError(
                f"API error: {response.status_code} - {response.text}",
                status_code=response.status_code,
            )

    def _convert_camel_to_snake(self, data: dict) -> dict:
        def to_snake(name: str) -> str:
            result = []
            for i, char in enumerate(name):
                if char.isupper() and i > 0:
                    result.append("_")
                result.append(char.lower())
            return "".join(result)

        return {to_snake(k): v for k, v in data.items()}

    async def list_projects(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        pagination_mode: PaginationMode = PaginationMode.OFFSET,
        start_after: str | None = None,
    ) -> list[Project]:
        client = self._ensure_client()
        params: dict[str, str | int] = {"limit": limit}

        if pagination_mode == PaginationMode.CURSOR:
            params["paginationMode"] = "token"
            if start_after:
                params["startAfter"] = start_after
        else:
            params["offset"] = offset

        response = await client.get("/projects", params=params)
        self._handle_response_errors(response)

        data = response.json()
        projects_data = data.get("projects", [])
        return [Project(**self._convert_camel_to_snake(p)) for p in projects_data]

    async def get_project(self, project_id: str) -> Project:
        client = self._ensure_client()
        response = await client.get(f"/projects/{project_id}")
        self._handle_response_errors(response)
        return Project(**self._convert_camel_to_snake(response.json()))

    async def list_project_files(
        self,
        project_id: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        pagination_mode: PaginationMode = PaginationMode.OFFSET,
        start_after: str | None = None,
    ) -> list[ProjectFile]:
        client = self._ensure_client()
        params: dict[str, str | int] = {"limit": limit}

        if pagination_mode == PaginationMode.CURSOR:
            params["paginationMode"] = "token"
            if start_after:
                params["startAfter"] = start_after
        else:
            params["offset"] = offset

        response = await client.get(f"/projects/{project_id}/files", params=params)
        self._handle_response_errors(response)

        data = response.json()
        files_data = data.get("files", [])
        return [ProjectFile(**self._convert_camel_to_snake(f)) for f in files_data]

    async def get_company_members(
        self,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        pagination_mode: PaginationMode = PaginationMode.OFFSET,
        start_after: str | None = None,
    ) -> list[CompanyMember]:
        client = self._ensure_client()
        params: dict[str, str | int] = {"limit": limit}

        if pagination_mode == PaginationMode.CURSOR:
            params["paginationMode"] = "token"
            if start_after:
                params["startAfter"] = start_after
        else:
            params["offset"] = offset

        response = await client.get("/company/members", params=params)
        self._handle_response_errors(response)

        data = response.json()
        members_data = data.get("members", [])
        return [CompanyMember(**self._convert_camel_to_snake(m)) for m in members_data]

    async def get_current_member(self) -> CompanyMember:
        client = self._ensure_client()
        response = await client.get("/company/members/me")
        self._handle_response_errors(response)
        return CompanyMember(**self._convert_camel_to_snake(response.json()))

    async def iter_all_projects(self, page_size: int = DEFAULT_LIMIT) -> AsyncIterator[Project]:
        offset = 0
        while True:
            projects = await self.list_projects(limit=page_size, offset=offset)
            if not projects:
                break
            for project in projects:
                yield project
            offset += len(projects)

    async def iter_all_project_files(
        self, project_id: str, page_size: int = DEFAULT_LIMIT
    ) -> AsyncIterator[ProjectFile]:
        offset = 0
        while True:
            files = await self.list_project_files(project_id, limit=page_size, offset=offset)
            if not files:
                break
            for file in files:
                yield file
            offset += len(files)

    async def iter_all_company_members(
        self, page_size: int = DEFAULT_LIMIT
    ) -> AsyncIterator[CompanyMember]:
        offset = 0
        while True:
            members = await self.get_company_members(limit=page_size, offset=offset)
            if not members:
                break
            for member in members:
                yield member
            offset += len(members)
