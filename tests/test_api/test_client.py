import tempfile
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from craftnote_scraper.api import (
    CraftnoteAPIError,
    CraftnoteAuthenticationError,
    CraftnoteClient,
    CraftnoteNotFoundError,
    CraftnoteRateLimitError,
    FileType,
    PaginationMode,
    ProjectType,
)

TEST_API_KEY = "test-api-key"
TEST_BASE_URL = "https://api.example.com/api/v1"


@pytest.fixture
def client() -> CraftnoteClient:
    return CraftnoteClient(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)


class TestListProjects:
    @pytest.mark.asyncio
    async def test_returns_projects(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=100&offset=0",
            json={
                "projects": [
                    {
                        "id": "project-1",
                        "name": "Test Project",
                        "projectType": "PROJECT",
                        "archived": False,
                    },
                    {
                        "id": "project-2",
                        "name": "Test Folder",
                        "projectType": "FOLDER",
                        "projects": ["project-1"],
                        "archived": True,
                    },
                ]
            },
        )

        async with client:
            projects = await client.list_projects()

        assert len(projects) == 2
        assert projects[0].id == "project-1"
        assert projects[0].name == "Test Project"
        assert projects[0].project_type == ProjectType.PROJECT
        assert projects[0].archived is False
        assert projects[1].id == "project-2"
        assert projects[1].project_type == ProjectType.FOLDER
        assert projects[1].projects == ["project-1"]
        assert projects[1].archived is True

    @pytest.mark.asyncio
    async def test_with_pagination_offset(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=10&offset=20",
            json={"projects": []},
        )

        async with client:
            await client.list_projects(limit=10, offset=20)

    @pytest.mark.asyncio
    async def test_with_pagination_cursor(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=10&paginationMode=token&startAfter=abc123",
            json={"projects": []},
        )

        async with client:
            await client.list_projects(
                limit=10, pagination_mode=PaginationMode.CURSOR, start_after="abc123"
            )


class TestGetProject:
    @pytest.mark.asyncio
    async def test_returns_project(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects/project-1",
            json={
                "id": "project-1",
                "name": "Test Project",
                "projectType": "PROJECT",
                "orderNumber": "ORD-123",
                "street": "Main St 1",
                "zipcode": "12345",
                "city": "Berlin",
                "contacts": [{"name": "John Doe", "emails": ["john@example.com"], "phones": []}],
                "billingCity": "Munich",
                "parentProject": "folder-1",
            },
        )

        async with client:
            project = await client.get_project("project-1")

        assert project.id == "project-1"
        assert project.name == "Test Project"
        assert project.order_number == "ORD-123"
        assert project.city == "Berlin"
        assert project.billing_city == "Munich"
        assert project.parent_project == "folder-1"
        assert len(project.contacts) == 1
        assert project.contacts[0].name == "John Doe"


class TestListProjectFiles:
    @pytest.mark.asyncio
    async def test_returns_files(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects/project-1/files?limit=100&offset=0",
            json={
                "files": [
                    {
                        "id": "file-1",
                        "name": "document.pdf",
                        "projectId": "project-1",
                        "folderId": "folder-1",
                        "type": "DOCUMENT",
                        "creationTimestamp": 1609459200,
                        "size": 1024,
                    },
                    {
                        "id": "folder-1",
                        "name": "Documents",
                        "projectId": "project-1",
                        "folderId": None,
                        "type": "FOLDER",
                        "creationTimestamp": 1609459100,
                    },
                ]
            },
        )

        async with client:
            files = await client.list_project_files("project-1")

        assert len(files) == 2
        assert files[0].id == "file-1"
        assert files[0].name == "document.pdf"
        assert files[0].type == FileType.DOCUMENT
        assert files[0].folder_id == "folder-1"
        assert files[0].size == 1024
        assert files[1].type == FileType.FOLDER
        assert files[1].folder_id is None


class TestGetCompanyMembers:
    @pytest.mark.asyncio
    async def test_returns_members(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/company/members?limit=100&offset=0",
            json={
                "members": [
                    {
                        "id": "member-1",
                        "email": "john@example.com",
                        "name": "John",
                        "lastname": "Doe",
                        "mobile": "+49123456789",
                    }
                ]
            },
        )

        async with client:
            members = await client.get_company_members()

        assert len(members) == 1
        assert members[0].id == "member-1"
        assert members[0].email == "john@example.com"
        assert members[0].name == "John"
        assert members[0].lastname == "Doe"


class TestGetCurrentMember:
    @pytest.mark.asyncio
    async def test_returns_current_member(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/company/members/me",
            json={
                "id": "member-1",
                "email": "me@example.com",
                "name": "Current",
                "lastname": "User",
            },
        )

        async with client:
            member = await client.get_current_member()

        assert member.id == "member-1"
        assert member.email == "me@example.com"


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_authentication_error(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=f"{TEST_BASE_URL}/projects?limit=100&offset=0", status_code=401)

        async with client:
            with pytest.raises(CraftnoteAuthenticationError) as exc_info:
                await client.list_projects()

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_not_found_error(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=f"{TEST_BASE_URL}/projects/nonexistent", status_code=404)

        async with client:
            with pytest.raises(CraftnoteNotFoundError) as exc_info:
                await client.get_project("nonexistent")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=f"{TEST_BASE_URL}/projects?limit=100&offset=0", status_code=429)

        async with client:
            with pytest.raises(CraftnoteRateLimitError) as exc_info:
                await client.list_projects()

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_generic_api_error(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=100&offset=0",
            status_code=500,
            text="Internal Server Error",
        )

        async with client:
            with pytest.raises(CraftnoteAPIError) as exc_info:
                await client.list_projects()

        assert exc_info.value.status_code == 500


class TestClientInitialization:
    def test_raises_without_api_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent_secrets = Path(tmpdir) / "nonexistent.env"
            with pytest.raises(CraftnoteAuthenticationError):
                CraftnoteClient(secrets_path=nonexistent_secrets)

    def test_accepts_api_key(self):
        client = CraftnoteClient(api_key="test-key")
        assert client._api_key == "test-key"

    @pytest.mark.asyncio
    async def test_context_manager_required(self):
        client = CraftnoteClient(api_key="test-key")

        with pytest.raises(CraftnoteAPIError):
            await client.list_projects()


class TestIterAllProjects:
    @pytest.mark.asyncio
    async def test_iterates_all_pages(self, client: CraftnoteClient, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=2&offset=0",
            json={
                "projects": [
                    {"id": "a", "name": "Project A"},
                    {"id": "b", "name": "Project B"},
                ]
            },
        )
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=2&offset=2",
            json={
                "projects": [
                    {"id": "c", "name": "Project C"},
                ]
            },
        )
        httpx_mock.add_response(
            url=f"{TEST_BASE_URL}/projects?limit=2&offset=3",
            json={"projects": []},
        )

        async with client:
            projects = [p async for p in client.iter_all_projects(page_size=2)]

        assert len(projects) == 3
        assert [p.id for p in projects] == ["a", "b", "c"]
