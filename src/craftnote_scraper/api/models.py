from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProjectType(StrEnum):
    PROJECT = "PROJECT"
    FOLDER = "FOLDER"


class FileType(StrEnum):
    FOLDER = "FOLDER"
    DOCUMENT = "DOCUMENT"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"


class Contact(BaseModel):
    name: str | None = None
    emails: list[str] = []
    phones: list[str] = []


class CompanyMember(BaseModel):
    id: str
    email: str | None = None
    mobile: str | None = None
    name: str | None = None
    lastname: str | None = None


class Project(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    project_type: ProjectType | None = None
    order_number: str | None = None
    street: str | None = None
    zipcode: str | None = None
    city: str | None = None
    contacts: list[Contact] = []
    billing_city: str | None = None
    parent_project: str | None = None
    projects: list[str] = []
    archived: bool = False
    creation_date: int | None = None


class ProjectFile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    project_id: str
    folder_id: str | None = None
    type: FileType
    creation_timestamp: int | None = None
    last_modified_timestamp: int | None = None
    size: int | None = None
