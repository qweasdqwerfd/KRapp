from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import get_db
from app.core.security import verify_password, create_access_token, get_password_hash
from app.models.entities import User, Role
from app.schemas.schemas import Token, UserResponse, LoginRequest
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Аутентификация и роли (Задание 1)"])

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User).where(User.username == form_data.username)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Учетная запись заблокирована")

    role_stmt = select(Role).where(Role.id == user.role_id)
    role_res = await db.execute(role_stmt)
    role = role_res.scalars().first()

    access_token = create_access_token(data={"sub": user.username, "role": role.name})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": role.name,
        "username": user.username
    }

@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    role_stmt = select(Role).where(Role.id == current_user.role_id)
    role_res = await db.execute(role_stmt)
    role = role_res.scalars().first()

    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role_name": role.name if role else "UNKNOWN",
        "is_active": current_user.is_active
    }

