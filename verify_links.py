# verify_links.py
from pymongo import MongoClient

MONGO_URI = "mongodb+srv://Digitaldoncodes:digitaldoncodesx@know-thyself.1m8vekk.mongodb.net/portal"
client = MongoClient(MONGO_URI)
db = client["portal"]

for app in db.applications.find({}, {"_id": 1, "photo_url": 1, "resume_url": 1}).limit(5):
    print({
        "_id": app["_id"],
        "resume_url": app.get("resume_url"),
        "photo_url": app.get("photo_url")
    })