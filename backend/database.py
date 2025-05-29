import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017/main_db")
mongo_client = AsyncIOMotorClient(MONGO_URI)
main_db = mongo_client.get_default_database()
