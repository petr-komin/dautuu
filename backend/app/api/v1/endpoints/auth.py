from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
import uuid

from app.core.security import verify_password, get_password_hash, create_access_token
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str

    model_config = {"from_attributes": True}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Uživatel s tímto emailem již existuje",
        )

    if len(body.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Heslo musí mít alespoň 6 znaků",
        )

    user = User(email=body.email, hashed_password=get_password_hash(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nesprávný email nebo heslo",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


class ApiKeyResponse(BaseModel):
    api_key: uuid.UUID
    user_id: uuid.UUID


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/api-key", response_model=ApiKeyResponse)
async def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Vygeneruje (nebo přegeneruje) MCP API klíč pro přihlášeného uživatele.

    Klíč se použije jako Bearer token pro MCP endpoint:
      GET /api/v1/mcp/{user_id}/sse
      Authorization: Bearer <api_key>
    """
    current_user.api_key = uuid.uuid4()
    await db.commit()
    await db.refresh(current_user)
    return ApiKeyResponse(api_key=current_user.api_key, user_id=current_user.id)


@router.get("/api-key", response_model=ApiKeyResponse)
async def get_api_key(current_user: User = Depends(get_current_user)):
    """Vrátí aktuální MCP API klíč. Pokud nebyl vygenerován, vrátí 404."""
    if not current_user.api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API klíč nebyl dosud vygenerován. Použij POST /auth/api-key.",
        )
    return ApiKeyResponse(api_key=current_user.api_key, user_id=current_user.id)
