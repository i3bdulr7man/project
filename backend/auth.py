from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from fastapi import Cookie, HTTPException, status, Depends
from database import main_db
from typing import Optional
import os

# إعدادات التشفير
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY")  # غيّره في الإنتاج!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # أسبوع

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

async def get_current_user(token: str = Cookie(default=None)):
    if not token:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    user = await main_db.users.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return username

async def is_admin(username: str):
    user = await main_db.users.find_one({"username": username})
    return user and user.get("is_admin", False)

async def is_last_admin(username: str):
    admin_count = await main_db.users.count_documents({"is_admin": True})
    user = await main_db.users.find_one({"username": username})
    return user and user.get("is_admin", False) and admin_count == 1

def validate_api_secret(secret: str):
    # يمكنك تخصيص الشروط حسب متطلبات Nightscout
    return len(secret) >= 12
