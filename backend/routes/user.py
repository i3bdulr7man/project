from fastapi import APIRouter, Request, Depends, Cookie, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from jose import jwt
import httpx
import os
import aiosmtplib
from email.message import EmailMessage

from database import main_db
from auth import get_current_user, hash_password, verify_password, create_access_token, validate_api_secret
from docker_utils import create_nightscout_instance, delete_nightscout_instance

SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "nst1d.com")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL")

templates = Jinja2Templates(directory="templates")
router = APIRouter()

async def send_to_hubspot_contact_api(username: str, email: str, created_at: datetime):
    access_token = os.getenv("HUBSPOT_TOKEN")
    url = "https://api.hubapi.com/crm/v3/objects/contacts"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "properties": {
            "email": email,
            "firstname": username
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            print("HubSpot response:", response.status_code, response.text)
    except Exception as e:
        print("Failed to send contact to HubSpot:", e)

def create_email_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=1)
    payload = {"sub": email, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def send_verification_email(to_email: str, verify_link: str):
    print("📧 START send_verification_email")
    print("To:", to_email)
    print("Verify link:", verify_link)
    print("MAILGUN_API_KEY?", bool(os.getenv("MAILGUN_API_KEY")))
    api_key = os.getenv("MAILGUN_API_KEY")
    domain = os.getenv("MAILGUN_DOMAIN")
    from_email = os.getenv("FROM_EMAIL")

    if not api_key or not domain:
        print("❌ Mailgun API config is missing.")
        return

    url = f"https://api.mailgun.net/v3/{domain}/messages"
    auth = ("api", api_key)

    data = {
        "from": from_email,
        "to": [to_email],
        "subject": "تأكيد بريدك الإلكتروني",
        "text": f"مرحباً،\n\nيرجى تأكيد بريدك الإلكتروني عبر الرابط التالي:\n{verify_link}\n\nشكراً."
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, auth=auth, data=data)
            print("📤 Mailgun API Response:", response.status_code, response.text)
    except Exception as e:
        print("❌ Mailgun API Failed:", e)


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(request: Request, token: str = Query(...)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise Exception("Invalid token")
        await main_db.users.update_one({"email": email}, {"$set": {"is_verified": True}})
        message = "تم تأكيد بريدك الإلكتروني بنجاح. يمكنك الآن تسجيل الدخول."
    except Exception as e:
        message = f"فشل التحقق من البريد الإلكتروني: {str(e)}"

    return templates.TemplateResponse("email_verification.html", {
        "request": request,
        "message": message
    })


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_get(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request, "error": None})

@router.post("/forgot-password")
async def forgot_password_post(request: Request, email: str = Form(...)):
    user = await main_db.users.find_one({"email": email})
    if not user:
        return templates.TemplateResponse("forgot_password.html", {"request": request, "error": "البريد غير مسجل."})

    token = create_email_token(email)
    reset_link = f"https://{BASE_DOMAIN}/reset-password?token={token}"
    await send_verification_email(email, reset_link)

    return templates.TemplateResponse("forgot_password.html", {"request": request, "error": "تم إرسال رابط إعادة التعيين إلى بريدك."})

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_get(request: Request, token: str = Query(...)):
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": None})

@router.post("/reset-password")
async def reset_password_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...)
):
    if not token or not password or not password2:
        return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": "جميع الحقول مطلوبة."})

    if password != password2:
        return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": "كلمتا المرور غير متطابقتين."})

    if not validate_api_secret(password):
        return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": "كلمة المرور غير صالحة. يجب أن تكون بين 12 و 64 حرفاً."})

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        user = await main_db.users.find_one({"email": email})
        if not user:
            raise Exception("المستخدم غير موجود")

        username = user["username"]
        new_hashed_pw = hash_password(password)
        await main_db.users.update_one({"email": email}, {"$set": {"password": new_hashed_pw}})

        instance = await main_db.instances.find_one({"owner": username})
        if instance:
            delete_nightscout_instance(instance["container_name"])
            await main_db.instances.delete_one({"owner": username})

        return templates.TemplateResponse("login.html", {"request": request, "error": "تم تغيير كلمة المرور. يمكنك الآن تسجيل الدخول."})
    except Exception as e:
        return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": str(e)})


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, username: str = Depends(get_current_user)):
    instance = await main_db.instances.find_one({"owner": username})
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
        "instance": instance,
        "error": None
    })

@router.get("/register", response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})

@router.post("/register")
async def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    email: str = Form(...)
):
    if password != password2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "كلمتا المرور غير متطابقتين"
        })

    if not validate_api_secret(password):
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "كلمة المرور (api_secret) يجب أن تكون 12 حرفًا على الأقل"
        })

    user = await main_db.users.find_one({"username": username})
    if user:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "اسم المستخدم موجود بالفعل"
        })

    existing_email = await main_db.users.find_one({"email": email})
    if existing_email:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "البريد الإلكتروني مستخدم بالفعل"
        })

    created_at = datetime.utcnow()
    hashed_pw = hash_password(password)

    await main_db.users.insert_one({
        "username": username,
        "password": hashed_pw,
        "email": email,
        "is_admin": False,
        "is_verified": False,
        "created_at": created_at
    })

    token = create_email_token(email)
    verify_link = f"https://{BASE_DOMAIN}/verify-email?token={token}"

    await send_verification_email(email, verify_link)
    await send_to_hubspot_contact_api(username, email, created_at)

    return templates.TemplateResponse("register.html", {
        "request": request,
        "error": f"تم التسجيل بنجاح. تحقق من بريدك الإلكتروني."
    })

@router.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    user = await main_db.users.find_one({"username": username})
    if not user or not verify_password(password, user["password"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "بيانات الدخول غير صحيحة"
        })
    if not user.get("is_verified", False):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "يرجى التحقق من بريدك الإلكتروني أولاً."
        })
    access_token = create_access_token({"sub": username})
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(key="token", value=access_token, httponly=True)
    response.set_cookie(key="userpw", value=password, httponly=True)
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("token")
    response.delete_cookie("userpw")
    return response

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, username: str = Depends(get_current_user)):
    instance = await main_db.instances.find_one({"owner": username})
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
        "instance": instance,
        "error": None
    })

@router.post("/create_instance")
async def create_instance(
    request: Request,
    username: str = Depends(get_current_user),
    userpw: str = Cookie(default=None),
    show_forecast: str = Form(default="")
):
    if not userpw:
        return RedirectResponse("/login", status_code=302)

    instance = await main_db.instances.find_one({"owner": username})
    if instance:
        return RedirectResponse("/dashboard", status_code=302)

    db_name = f"ns_user_{username}"
    subdomain = username.lower()
    instance_name = f"ns_{username}"
    mongo_uri = f"mongodb://app_user:Fantokh1990@20.246.81.129:27017/main_db?authSource=admin"


    try:
        extra_env = {
            "ENABLE": "careportal basal dbsize rawbg iob maker bridge cob bwp cage iage sage boluscalc pushover treatmentnotify mmconnect loop pump profile food openaps bage alexa override cors",
            "SHOW_PLUGINS": "loop pump cob iob sage cage careportal basal override dbsize openaps",
            "DEVICESTATUS_ADVANCED": "true",
            "SHOW_FORECAST": show_forecast.strip()
        }

        container = create_nightscout_instance(instance_name, subdomain, mongo_uri, api_secret=userpw, extra_env=extra_env)
        await main_db.instances.insert_one({
            "owner": username,
            "container_name": instance_name,
            "subdomain": subdomain,
            "db_name": db_name,
            "created_at": datetime.utcnow(),
            "settings": extra_env
        })
    except Exception as e:
        print("Error creating instance:", e)
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "username": username,
            "instance": None,
            "error": "فشل إنشاء المثيل. يرجى المحاولة لاحقًا."
        })
    return RedirectResponse("/dashboard", status_code=302)

@router.post("/delete_instance")
async def delete_instance(
    request: Request,
    username: str = Depends(get_current_user)
):
    instance = await main_db.instances.find_one({"owner": username})
    if instance:
        delete_nightscout_instance(instance["container_name"])
        await main_db.instances.delete_one({"owner": username})
    return RedirectResponse("/dashboard", status_code=302)
