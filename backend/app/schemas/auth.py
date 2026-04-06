from pydantic import BaseModel
from app.schemas.usuario import UsuarioResponse


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UsuarioResponse


class RefreshRequest(BaseModel):
    refresh_token: str
