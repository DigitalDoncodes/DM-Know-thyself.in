#!/usr/bin/env python3
"""
Bulk-import students into the Job-Portal MongoDB (no pandas required).
Make sure your `students.csv` is in the same directory.

CSV format (UTF-8, comma-separated, header row required):
student_id,name,email,phone
23BPY001,Aayeesha Mullick K,aayeeshamullic.23bpy@kclas.ac.in,6382693365
23BPY002,Ablin Jebisha J,ablinjebisha.23bpy@kclas.ac.in,9385446175
...
"""

import os
import sys
import csv
import datetime
from pymongo import MongoClient
from passlib.hash import bcrypt
from dotenv import load_dotenv


def main() -> None:
    # ---- Load config from .env ----
    load_dotenv()
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/portal")

    # ---- Locate CSV ----
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "students.csv"
    if not os.path.isfile(csv_path):
        print(f"[ERROR] File not found: {csv_path}")
        sys.exit(1)

    # ---- Read CSV ----
    records = []
    required_headers = {"student_id", "name", "email", "phone"}
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            # Check headers
            if not required_headers.issubset(set(reader.fieldnames)):
                print(f"[ERROR] CSV must contain columns: {', '.join(required_headers)}")
                sys.exit(1)
            
            # Process each row
            for row_num, row in enumerate(reader, start=2):  # start=2 (row 1 is header)
                # Skip empty rows
                if not any(row.values()):
                    print(f"[WARNING] Skipping row {row_num}: missing required data")
                    continue
                    
                # Clean and validate data
                student_id = str(row["student_id"]).strip()
                name = str(row["name"]).strip()
                email = str(row["email"]).strip().lower()
                phone = str(row["phone"]).strip().replace(" ", "").replace("-", "")
                
                # Skip rows with missing critical data
                if not all([student_id, name, email, phone]):
                    print(f"[WARNING] Skipping row {row_num}: missing required data")
                    continue
                
                records.append({
                    "role": "student",
                    "student_id": student_id.upper(),
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "pw_hash": bcrypt.hash(phone),  # phone number = password
                    "created_at": datetime.datetime.now(datetime.timezone.utc),  # timezone-aware
                })
                
    except FileNotFoundError:
        print(f"[ERROR] File not found: {csv_path}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Error reading CSV: {e}")
        sys.exit(1)

    if not records:
        print("[INFO] No valid records to import.")
        return

    # ---- Insert into MongoDB ----
    try:
        client = MongoClient(MONGO_URI)
        db = client.get_default_database()
        if db is None:  # explicit check – don't use "or" here
            db = client["portal"]

        # Optional: create unique indexes
        try:
            db.users.create_index("email", unique=True)
            db.users.create_index("student_id", unique=True)
        except Exception:
            pass  # Indexes might already exist

        # Insert records
        result = db.users.insert_many(records, ordered=False)
        print(f"[OK] Successfully imported {len(result.inserted_ids)} students.")
        
    except Exception as e:
        print(f"[ERROR] Database error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
