# check_drive_links.py
from pymongo import MongoClient

MONGO_URI = "mongodb+srv://Digitaldoncodes:digitaldoncodesx@know-thyself.1m8vekk.mongodb.net/portal"
client = MongoClient(MONGO_URI)
db = client["portal"]

print("🔎 Checking applications collection...\n")

for app in db.applications.find({}, {"student_id": 1, "photo_url": 1, "resume_url": 1}).limit(10):
    print(f"Student: {app.get('student_id', 'N/A')}")
    print(f"📷 Photo link: {app.get('photo_url', 'None')}")
    print(f"📄 Resume link: {app.get('resume_url', 'None')}")
    print("-" * 60)