#!/usr/bin/env python3
from app import users_col, send_brevo_email
from werkzeug.security import generate_password_hash
import time

TEMP_PW = "password1234"
PW_HASH = generate_password_hash(TEMP_PW)

cursor = users_col.find({"role": "student"})
total = users_col.count_documents({"role": "student"})
print("Users to reset:", total)
confirm = input("Proceed? (yes/no): ").strip().lower()
if confirm not in ("y","yes"):
    exit(0)

for u in cursor:
    try:
        users_col.update_one({"_id": u["_id"]}, {"$set": {"password_hash": PW_HASH, "force_password_reset": True}})
        email = u.get("email")
        name = u.get("name", "")
        if email:
            html = f"<p>Hi {name or 'Student'},</p><p>Your password has been reset to <b>{TEMP_PW}</b>. You will be required to change it on next login.</p>"
            send_brevo_email(email, name, "Know-Thyself — Password Reset", html, sync=True)
            print("Updated+emailed:", email)
        else:
            print("Updated (no email):", u["_id"])
        time.sleep(0.15)
    except Exception as e:
        print("Error for", u.get("email"), e)