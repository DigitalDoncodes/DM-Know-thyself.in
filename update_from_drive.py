# update_from_drive.py
import csv
from pymongo import MongoClient

MONGO_URI = "mongodb+srv://Digitaldoncodes:digitaldoncodesx@know-thyself.1m8vekk.mongodb.net/portal"
client = MongoClient(MONGO_URI)
db = client["portal"]
applications = db.applications

print("🚀 Starting to update Google Drive links...\n")

with open("drive_links.csv", newline="") as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        student_id = row.get("student_id")
        photo_url = row.get("photo_url")
        resume_url = row.get("resume_url")

        if not student_id:
            continue

        update_data = {}
        if photo_url:
            update_data["photo_url"] = photo_url
        if resume_url:
            update_data["resume_url"] = resume_url

        if update_data:
            result = applications.update_many({"student_id": student_id}, {"$set": update_data})
            if result.modified_count > 0:
                for field in update_data.keys():
                    print(f"✅ Updated {student_id} → {field}")
            else:
                print(f"⚠️ No user found for {student_id}")

print("\n🎯 All Drive links processed successfully!")       