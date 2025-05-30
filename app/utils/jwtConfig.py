from datetime import datetime,timezone,timedelta
import jwt
from app.configurations.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_MINUTES, \
    EMAIL_TOKEN_EXPIRE_MINUTES


def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)  # Refresh token valid for 30 days
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_access_token(data: dict):
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    encoded_jwt = jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_email_token(email: str) -> str:
    expire = datetime.now(timezone.utc)  + timedelta(minutes=EMAIL_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": email, "exp": expire}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_email_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return "Token expired"
    except jwt.PyJWTError:
        return "Invalid token"
