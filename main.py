from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers.auth import router as auth_router
from routers.admin import router as admin_router
from routers.user import router as user_router

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(user_router)