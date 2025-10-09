import csv
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["portal"]
applications_col = db["applications"]

def drive_link(file_id):
    return f"https://drive.google.com/uc?export=view&id={file_id}"

with open("drive_links.csv", newline="") as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        filename = row["Filename"]
        file_id = row["File ID"]

        # Detect file type
        if "photo" in filename.lower():
            field = "photo_url"
        elif "resume" in filename.lower():
            field = "resume_url"
        else:
            continue

        # Extract student ID from filename (e.g., "23BPY017_photo.jpg")
        student_id = filename.split("_")[0].strip()

        # Update record based on student_id field
        result = applications_col.update_one(
            {"student_id": student_id},  # Change this to "roll_no" if needed
            {"$set": {field: drive_link(file_id)}}
        )

        if result.modified_count > 0:
            print(f"✅ Updated {student_id} → {field}")
        else:
            print(f"⚠️ No match found for {student_id}")

print("\n🎯 All Google Drive links updated successfully!")