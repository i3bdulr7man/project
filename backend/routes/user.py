from fastapi import APIRouter, Request, Depends, Cookie, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import httpx
import os

from database import main_db
from auth import get_current_user, hash_password, verify_password, create_access_token, validate_api_secret
from docker_utils import create_nightscout_instance, delete_nightscout_instance

templates = Jinja2Templates(directory="templates")
router = APIRouter()

#HubSpot
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
            "firstname": username,
            "createdate": created_at.isoformat()
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            print("HubSpot response:", response.status_code, response.text)
    except Exception as e:
        print("Failed to send contact to HubSpot:", e)

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, username: str = Depends(get_current_user)):
    instance = await main_db.instances.find_one({"owner": username})
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": username,
        "instance": instance,
        "error": None
    })
##

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
    
    created_at = datetime.utcnow()
    hashed_pw = hash_password(password)
    await main_db.users.insert_one({
        "username": username,
        "password": hashed_pw,
        "email": email,
        "is_admin": False,
        "created_at": created_at
    })

    await send_to_hubspot_contact_api(username, email, created_at)
    return RedirectResponse("/login", status_code=302)


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
    userpw: str = Cookie(default=None)
):
    if not userpw:
        return RedirectResponse("/login", status_code=302)

    instance = await main_db.instances.find_one({"owner": username})
    if instance:
        return RedirectResponse("/dashboard", status_code=302)

    db_name = f"ns_user_{username}"
    subdomain = username.lower()
    instance_name = f"ns_{username}"
    mongo_uri = f"mongodb://mongodb:27017/{db_name}"

    try:
        container = create_nightscout_instance(instance_name, subdomain, mongo_uri, api_secret=userpw)
        await main_db.instances.insert_one({
            "owner": username,
            "container_name": instance_name,
            "subdomain": subdomain,
            "db_name": db_name,
            "created_at": datetime.utcnow()
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
