import os
import datetime
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/portal")
client = MongoClient(MONGO_URI)
db = client.get_default_database()

if db is None:
    db = client["portal"]

# *** STEP 1: Find your teacher's ObjectId first ***
# Run this to find your teacher's ObjectId:
def find_teacher_id():
    print("Finding teachers in the database:")
    print("=" * 50)
    teachers = db.users.find({"role": "teacher"})
    for teacher in teachers:
        print(f"Name: {teacher.get('name', 'N/A')}")
        print(f"Email: {teacher.get('email', 'N/A')}")
        print(f"ObjectId: {teacher['_id']}")
        print("-" * 30)

# Uncomment the line below to find your teacher ID first
# find_teacher_id()

# *** STEP 2: Replace this with your actual teacher's ObjectId ***
TEACHER_USER_ID = "6882603d9952e3cb1c4e78fc"  # Replace with actual ObjectId from Step 1

def clear_and_import_jobs():
    # Clear existing jobs for this teacher (optional)
    deleted_count = db.jobs.delete_many({"created_by": ObjectId(TEACHER_USER_ID)}).deleted_count
    print(f"Deleted {deleted_count} existing jobs")
    
    # Job data
    jobs = [
        {"title": "Scientist B, DIPR, DRDO", "description": "Research position at the Defence Institute of Psychological Research, DRDO.", "vacancies": 1},
        {"title": "Assistant Professor, State Govt University", "description": "Teaching psychology and conducting research at a state government university.", "vacancies": 2},
        {"title": "Manager, L & D, A manufacturing company", "description": "Manage learning and development activities for employees in a manufacturing company.", "vacancies": 1},
        {"title": "Clinical Psychologist", "description": "Specialist in learning difficulties and ADHD interventions.", "vacancies": 1},
        {"title": "Course Developer / Instructional Designer", "description": "Develop online psychology courses for platforms such as SWAYAM, NPTEL, or Coursera.", "vacancies": 1},
        {"title": "Program Manager â€“ Mental Health (NGOs)", "description": "Manage field research and outreach programs for NGOs like Sangath or The Live Love Laugh Foundation.", "vacancies": 1},
        {"title": "Mental Health Coach / Digital Therapist", "description": "Provide digital therapy or coaching on platforms such as MindPeers, YourDOST, or BetterLYF.", "vacancies": 2},
        {"title": "Youth Program Officer â€“ UNESCO, Pratham", "description": "Coordinate adolescent well-being and life skills programs.", "vacancies": 1},
        {"title": "AI Ethics Consultant", "description": "Work on human behavior and AI alignment for organizations like Google DeepMind or Microsoft Research.", "vacancies": 1},
        {"title": "Performance Coach â€“ SUSER_IDports & High-Pressure Professions", "description": "Support athletes, musicians, or students in high-pressure environments.", "vacancies": 1},
    ]
    
    # Insert jobs with proper created_by field
    now = datetime.datetime.now(datetime.timezone.utc)
    inserted_jobs = []
    
    for job in jobs:
        job["status"] = "open"
        job["created_at"] = now
        
        result = db.jobs.insert_one(job)
        inserted_jobs.append(result.inserted_id)
    
    print(f"Successfully inserted {len(inserted_jobs)} jobs with proper created_by field")
    return len(inserted_jobs)

# *** STEP 3: Run the import (only after setting TEACHER_USER_ID) ***
if TEACHER_USER_ID != "6882603d9952e3cb1c4e78fc":
    clear_and_import_jobs()
else:
    print("Please set TEACHER_USER_ID to your actual teacher's ObjectId first!")
    print("Uncomment find_teacher_id() to find it.")