# reset_password.py
from werkzeug.security import generate_password_hash
from pymongo import MongoClient

# replace with your MongoDB URI / db name
client = MongoClient("mongodb://user:pass@localhost:27017/")
db = client.get_database("portal")
users_col = db.users

email = "dhatchinamoorthi.23bpy@kclas.ac.in"
new_password = "9363632214"   # choose a secure password

new_hash = generate_password_hash(new_password)  # PBKDF2 by default via werkzeug

res = users_col.update_one({"email": email}, {"$set": {"password_hash": new_hash}})
if res.matched_count:
    print("Password reset. Login with:", new_password)
else:
    print("User not found.")