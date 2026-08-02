from pydantic import BaseModel


class CapabilityOut(BaseModel):
    key: str
    label: str
    category: str
    is_write: bool
    module_code: str | None = None
    risk: str

    class Config:
        from_attributes = True


class RoleCapabilityOut(BaseModel):
    role: str
    capability_key: str
    allowed: bool

    class Config:
        from_attributes = True


class RoleCapabilityEdit(BaseModel):
    """One cell of the matrix -- role x capability_key -> allowed."""
    role: str
    capability_key: str
    allowed: bool


class RoleCapabilityMatrix(BaseModel):
    """Full tenant matrix, keyed by role -> list of entries. Rows for every
    (role, capability_key) pair the tenant has, not just the granted ones --
    the settings UI needs to render every cell, on or off."""
    entries: list[RoleCapabilityOut]


class RoleCapabilityMatrixUpdate(BaseModel):
    """PUT body -- caller sends only the cells that changed."""
    edits: list[RoleCapabilityEdit]
