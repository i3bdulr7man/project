from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from database import main_db
from auth import get_current_user, is_admin, is_last_admin
from docker_utils import delete_nightscout_instance

templates = Jinja2Templates(directory="templates")
router = APIRouter()

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, username: str = Depends(get_current_user)):
    if not await is_admin(username):
        raise HTTPException(status_code=403, detail="غير مصرح لك بالدخول")
    instances = await main_db.instances.find().to_list(100)
    users = await main_db.users.find().to_list(100)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "username": username,
        "instances": instances,
        "users": users
    })

@router.post("/admin/delete_user")
async def admin_delete_user(
    request: Request,
    username: str = Depends(get_current_user),
    target_username: str = Form(...)
):
    if not await is_admin(username):
        raise HTTPException(status_code=403, detail="غير مصرح لك")
    if await is_last_admin(target_username):
        return RedirectResponse("/admin", status_code=302)
    await main_db.users.delete_one({"username": target_username})
    await main_db.instances.delete_many({"owner": target_username})
    return RedirectResponse("/admin", status_code=302)



from pymongo import MongoClient

def delete_user_database(username):
    db_name = f"ns_user_{username}"
    mongo_uri = "mongodb://app_user:Fantokh1990@20.246.81.129:27017/?authSource=admin"
    client = MongoClient(mongo_uri)
    client.drop_database(db_name)
    
@router.post("/admin/delete_instance")
async def admin_delete_instance(
    request: Request,
    username: str = Depends(get_current_user),
    container_name: str = Form(...)
):
    if not await is_admin(username):
        raise HTTPException(status_code=403, detail="غير مصرح لك")
    delete_nightscout_instance(container_name)
    await main_db.instances.delete_one({"container_name": container_name})
    delete_user_database(username)
    return RedirectResponse("/admin", status_code=302)
