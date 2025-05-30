import logging
from typing import Annotated
from redis.asyncio import Redis
import jwt
from fastapi import APIRouter, Request, status, Depends, Cookie, Response, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.templating import Jinja2Templates

from app.configurations.config import (
    SECRET_KEY, ALGORITHM, FULLDOMAIN,
    GLOBAL_PASSWORD, REDIS_URL
)
from app.configurations.database import get_async_session
from app.models.models import User
from app.schemas.schemas import (
    UserLogin, UserRegistration, UserPasswordConfirm, PasswordCheckRequest
)
from app.utils.hashing import (
    verify_password, confirm_password, get_password_hash
)
from app.broker.tasks import send_email
from app.utils.jwtConfig import (
    create_access_token, create_email_token,
    create_refresh_token, verify_email_token
)
from app.configurations.google_config import get_google_user_info, get_google_login_url
from app.utils.exception import RedirectToHomeException

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BLOCK_TIME_SECONDS = 300

templates = Jinja2Templates(directory="app/templates")
redis = Redis.from_url(REDIS_URL, decode_responses=True)
auth_router = APIRouter(tags=["Authentication"], include_in_schema=False)
security = HTTPBearer(auto_error=False)

# --------------------------- UTILS ---------------------------

async def find_user_by_email(email: str, session: AsyncSession):
    query = select(User).where(User.email == email).options(
        selectinload(User.address), selectinload(User.reports)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()

async def prepare_email_with_token(token_type: str, email: str) -> str:
    token = create_email_token(email)
    return f"<a href='{FULLDOMAIN}auth/{token_type}/{token}'>Click here to {token_type}</a>"

def verify_global_password_cookie(request: Request):
    if request.cookies.get("pending_global_password") == "1":
        raise RedirectToHomeException()

# ----------------------- GLOBAL PASSWORD -----------------------

@auth_router.post("/check_global_password")
async def check_global_password(
    request: Request,
    data: PasswordCheckRequest,
    response: Response,
):
    client_ip = request.client.host
    redis_key = f"global_pwd_fail:{client_ip}"

    attempts = await redis.get(redis_key)
    if attempts and int(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    if data.password == GLOBAL_PASSWORD:
        await redis.delete(redis_key)
        response.delete_cookie("pending_global_password", path="/")
        return {"message": "Password accepted"}

    await redis.incr(redis_key)
    await redis.expire(redis_key, BLOCK_TIME_SECONDS)
    raise HTTPException(status_code=401, detail="Wrong password")

# --------------------------- LOGIN ----------------------------

@auth_router.get("/login")
async def login_page(request: Request, msg: str | None = ""):
    return templates.TemplateResponse("login.html", {
        "request": request,
        "google_login_url": get_google_login_url(),
        "msg": msg
    })

@auth_router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    user_login: Annotated[UserLogin, Depends(UserLogin.as_form)],
    session: AsyncSession = Depends(get_async_session),
):
    user = await find_user_by_email(user_login.email, session)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "msg": "User does not exist"})

    if user.hashed_password is None:
        return templates.TemplateResponse("register.html", {"request": request, "msg": "Please register first"})

    if not verify_password(user_login.password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Incorrect password"})

    if not user.isVerified:
        html_message = await prepare_email_with_token("verify", user.email)
        send_email.apply_async(args=[[user.email], "Verify your email", html_message])
        return templates.TemplateResponse("login.html", {"request": request, "msg": "Verification email resent"})
    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie("refresh_token", refresh_token, httponly=True,secure=True, samesite="Strict")
    response.set_cookie("pending_global_password", "1", path="/", httponly=False,secure=True, samesite="Strict")
    response.headers["Authorization"] = f"Bearer {access_token}"
    return response

# -------------------------- REGISTER --------------------------

@auth_router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@auth_router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    register_user: Annotated[UserRegistration, Depends(UserRegistration.as_form)],
    session: AsyncSession = Depends(get_async_session)
):
    existing_user = await find_user_by_email(register_user.email, session)

    if not confirm_password(register_user.hashed_password, register_user.confirm_password):
        return templates.TemplateResponse("register.html", {"request": request, "msg": "Passwords do not match"})

    if existing_user:
        if existing_user.hashed_password and existing_user.isVerified:
            return templates.TemplateResponse("register.html", {"request": request, "msg": "User already exists"})
        if existing_user.hashed_password is None and existing_user.isVerified:
            existing_user.hashed_password = get_password_hash(register_user.confirm_password)
            await session.commit()
            return templates.TemplateResponse("login.html", {"request": request, "msg": "registered"})

    html_message = await prepare_email_with_token("verify", register_user.email)
    send_email.apply_async(args=[[register_user.email], "Verify your email", html_message])
    register_user.hashed_password = get_password_hash(register_user.confirm_password)
    session.add(User(**register_user.model_dump()))
    await session.commit()
    return templates.TemplateResponse("login.html", {"request": request, "msg": "sent"})

# ---------------------- PASSWORD RECOVERY ----------------------

@auth_router.get("/forgot_password", response_class=HTMLResponse)
async def forgot_password(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request})

@auth_router.post("/request_for_password", response_class=HTMLResponse)
async def request_for_password(
    request: Request,
    email: str = Form(),
    session: AsyncSession = Depends(get_async_session)
):
    user = await find_user_by_email(email, session)
    if not user:
        return templates.TemplateResponse("forgot_password.html", {"request": request, "msg": "User not found"})

    user.isVerified = False
    await session.commit()
    html_message = await prepare_email_with_token("recovery", user.email)
    send_email.apply_async(args=[[user.email], "Password Recovery", html_message])
    return templates.TemplateResponse("login.html", {"request": request, "msg": "recovery"})

@auth_router.get("/recovery/{token}", response_class=HTMLResponse)
async def recover_user_account(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_async_session)
):
    email = verify_email_token(token)
    if email == "Token expired":
        return templates.TemplateResponse("forgot_password.html", {"request": request, "msg": "Token expired"})
    elif email == "Invalid token":
        return templates.TemplateResponse("reset_password.html", {"request": request, "msg": "Invalid token"})

    user = await find_user_by_email(email, session)
    user.hashed_password = None
    return templates.TemplateResponse("reset_password.html", {"request": request, "email": user.email})

@auth_router.post("/password_confirmed", response_class=HTMLResponse)
async def confirmed_page(
    request: Request,
    user_confirm: Annotated[UserPasswordConfirm, Depends(UserPasswordConfirm.as_form)],
    session: AsyncSession = Depends(get_async_session)
):
    user = await find_user_by_email(user_confirm.email, session)
    if not user:
        return templates.TemplateResponse("token_expired.html", {"request": request, "msg": "Token expired"})

    if not confirm_password(user_confirm.password1, user_confirm.password2):
        return templates.TemplateResponse("reset_password.html", {
            "request": request,
            "email": user.email,
            "msg": "Passwords do not match"
        })

    user.hashed_password = get_password_hash(user_confirm.password1)
    user.isVerified = True
    await session.commit()
    return templates.TemplateResponse("login.html", {"request": request, "msg": "changed"})

# ------------------------- VERIFY EMAIL -------------------------

@auth_router.get("/verify/{token}", response_class=HTMLResponse)
async def verify_user_account(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_async_session)
):
    email = verify_email_token(token)
    if email == "Token expired":
        return templates.TemplateResponse("token_expired.html", {"request": request, "msg": "Token expired"})
    elif email == "Invalid token":
        return templates.TemplateResponse("token_expired.html", {"request": request, "msg": "Invalid token"})

    user = await find_user_by_email(email, session)
    user.isVerified = True
    await session.commit()
    return templates.TemplateResponse("login.html", {"request": request, "msg": "success"})

@auth_router.post("/resend", response_class=HTMLResponse)
async def resend_verification(
    request: Request,
    email: str = Form(),
    session: AsyncSession = Depends(get_async_session)
):
    user = await find_user_by_email(email, session)
    if not user:
        return templates.TemplateResponse("token_expired.html", {"request": request, "msg": "User does not exist"})

    html_message = await prepare_email_with_token("verify", user.email)
    send_email.apply_async(args=[[user.email], "Verify your email", html_message])
    return templates.TemplateResponse("login.html", {"request": request, "msg": "sent"})

# ------------------------- GOOGLE LOGIN -------------------------
@auth_router.get("/google/callback")
async def google_callback(
    code: str = None,
    error: str = None,
    session: AsyncSession = Depends(get_async_session)):
    if error == "access_denied" or code is None:
        return RedirectResponse(url="/auth/login")
    try:
        user_info = await get_google_user_info(code)
    except Exception:
        return RedirectResponse(url="/auth/login?error=google_fetch_failed")
    email = user_info['email'].lower()
    user = await find_user_by_email(email, session)
    if user:
        user.photo = user_info.get('picture', user.photo)
        user.firstname = user_info.get('given_name', user.firstname)
        user.lastname = user_info.get('family_name', user.lastname)
        user.isVerified = user_info.get('verified_email', user.isVerified)
    else:
        user = User(email=user_info['email'], firstname=user_info['given_name'], lastname=user_info['family_name'],
                    photo=user_info['picture'], isVerified=user_info['verified_email'])
    session.add(user)
    await session.commit()
    await session.refresh(user)
    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        max_age=7 * 24 * 60 * 60,
        secure=True,
        samesite="Strict"
    )
    response.set_cookie("pending_global_password", "1", path="/", httponly=False,secure=True, samesite="Strict")
    # Consider adding this token to the frontend via query string or JS-accessible cookie
    response.headers["Authorization"] = f"Bearer {access_token}"
    return response

# -------------------------- LOGOUT -----------------------------

@auth_router.get("/logout", response_class=HTMLResponse)
async def logout():
    response = RedirectResponse(url="/auth/login")
    response.delete_cookie("refresh_token")
    response.delete_cookie("pending_global_password")
    return response

# --------------------- TOKEN VALIDATION ------------------------

async def get_current_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    refresh_token: str = Cookie(None),
    session: AsyncSession = Depends(get_async_session)
):
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
            user = await find_user_by_email(email, session)
            if user:
                return user
        except InvalidTokenError:
            pass

    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            email = payload.get("sub")
        except InvalidTokenError:
            return None

        user = await find_user_by_email(email, session)
        if not user:
            return None

        new_access_token = create_access_token({"sub": user.email})
        new_refresh_token = create_refresh_token({"sub": user.email})
        response.set_cookie("refresh_token", new_refresh_token, httponly=True,secure=True, samesite="Strict")
        response.headers["Authorization"] = f"Bearer {new_access_token}"
        return user

    return None
