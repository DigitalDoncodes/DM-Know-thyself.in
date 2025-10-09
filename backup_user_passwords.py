#!/usr/bin/env python3
"""
backup_user_passwords.py

Export user password hashes from the `users` collection into timestamped CSV + JSON backups.
Optionally encrypt the JSON backup with Fernet (requires `cryptography` package).

Usage:
  # plain backup (no encryption)
  python3 backup_user_passwords.py

  # with environment variables
  MONGO_URI="mongodb://..." DB_NAME="portal" python3 backup_user_passwords.py

  # enable encryption (it will prompt for a key or use BACKUP_KEY env var)
  ENCRYPT_BACKUP=1 python3 backup_user_passwords.py
"""

import os
import sys
import csv
import json
import gzip
import getpass
from datetime import datetime
from pathlib import Path

try:
    from pymongo import MongoClient
except Exception as e:
    print("Missing dependency: pymongo. Install with `pip install pymongo`")
    raise

# Try import cryptography (optional)
CRYPT_AVAILABLE = False
FERNET = None
try:
    from cryptography.fernet import Fernet
    CRYPT_AVAILABLE = True
except Exception:
    CRYPT_AVAILABLE = False

# Config (can be overridden by environment)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://Digitaldoncodes:digitaldoncodesx@know-thyself.1m8vekk.mongodb.net")
DB_NAME = os.getenv("DB_NAME", "portal")
USERS_COLL = os.getenv("USERS_COLL", "users")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
ENCRYPT_BACKUP = os.getenv("ENCRYPT_BACKUP", "") in ("1", "true", "True", "yes", "YES")

# Ensure backup dir exists
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
csv_path = BACKUP_DIR / f"users_passwords_{ts}.csv"
json_path = BACKUP_DIR / f"users_passwords_{ts}.json"
json_gz_path = BACKUP_DIR / f"users_passwords_{ts}.json.gz"
json_enc_path = BACKUP_DIR / f"users_passwords_{ts}.json.encrypted"

def confirm(prompt="Proceed? (yes/no): "):
    r = input(prompt).strip().lower()
    return r in ("y", "yes")

def get_fernet_key_from_env_or_prompt():
    # Prefer BACKUP_KEY env var; if absent prompt user for a passphrase to derive a key.
    key_env = os.getenv("BACKUP_KEY")
    if key_env:
        # If the user supplied a Fernet key directly, use it; else if passphrase, derive?
        # We expect a base64 32-byte key here; if not, will prompt.
        try:
            Fernet(key_env)
            return key_env
        except Exception:
            # Not a valid Fernet key; ask for passphrase to derive.
            pass

    # Ask user to input or confirm generation
    print("")
    print("Encryption requested but no valid BACKUP_KEY env found.")
    print("You can either supply a Fernet key via BACKUP_KEY, or enter a passphrase (will be used to derive a key).")
    choice = input("Type 'g' to GENERATE a new random key (recommended), 'p' to use passphrase, or anything else to abort: ").strip().lower()
    if choice == "g":
        k = Fernet.generate_key().decode()
        print("")
        print("Generated key (STORE THIS SAFELY):")
        print(k)
        print("")
        ok = confirm("Saved key shown above? Copy it to a safe place now. Continue and use this key to decrypt backups later? (yes/no): ")
        if not ok:
            print("Aborted by user.")
            sys.exit(1)
        return k
    elif choice == "p":
        pw = getpass.getpass("Enter passphrase to derive key from (min 8 chars): ")
        # Simple derivation — PBKDF2 to 32-byte then base64. Use hashlib + salt.
        # NOTE: This derivation uses a fixed salt here; for production use a random salt saved with the file.
        import base64, hashlib
        if len(pw) < 4:
            print("Passphrase too short. Aborting.")
            sys.exit(1)
        salt = b"know-thyself-backup-salt"  # WARNING: for stronger security use random salt + store it with ciphertext
        kdf = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 390000, dklen=32)
        key = base64.urlsafe_b64encode(kdf)
        return key.decode()
    else:
        print("Encryption aborted.")
        sys.exit(1)

def main():
    print("Backup script starting.")
    print(f"Mongo URI: {MONGO_URI}")
    print(f"DB: {DB_NAME} | Collection: {USERS_COLL}")
    print(f"Backups will be saved to: {BACKUP_DIR.resolve()}")
    if ENCRYPT_BACKUP:
        print("Encryption: ENABLED")
        if not CRYPT_AVAILABLE:
            print("ERROR: cryptography package not available. Install with `pip install cryptography` or disable ENCRYPT_BACKUP.")
            sys.exit(1)
    else:
        print("Encryption: disabled (set ENCRYPT_BACKUP=1 to enable)")

    # Confirm
    if not confirm("Proceed to generate backups of user password hashes? (yes/no): "):
        print("Aborted.")
        sys.exit(0)

    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    users_col = db[USERS_COLL]

    # Query: all users (change filter if desired)
    query = {}  # e.g., {"role":"student"} to limit
    cursor = users_col.find(query)

    # Flatten output into list of dicts containing selected fields
    rows = []
    count = 0
    for u in cursor:
        count += 1
        doc = {
            "_id": str(u.get("_id")),
            "email": u.get("email"),
            "name": u.get("name"),
            # Common fields that may hold passwords/hashes in your app:
            "password_hash": u.get("password_hash"),
            "password_plain": u.get("password"),   # some older records may have plain password — unlikely but capture it
            "role": u.get("role"),
            "created_at": u.get("created_at").isoformat() if u.get("created_at") else None,
        }
        rows.append(doc)

    if count == 0:
        print("No user documents found with the given query. Exiting.")
        sys.exit(0)

    print(f"Collected {count} user records.")

    # Save CSV
    csv_fields = ["_id", "email", "name", "role", "password_hash", "password_plain", "created_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"CSV backup written -> {csv_path}")

    # Save JSON gzipped
    with gzip.open(json_gz_path, "wt", encoding="utf-8") as gz:
        json.dump(rows, gz, indent=2)
    print(f"GZipped JSON backup written -> {json_gz_path}")

    # Optionally also create an encrypted JSON (Fernet)
    if ENCRYPT_BACKUP:
        key = get_fernet_key_from_env_or_prompt()
        f = Fernet(key.encode() if isinstance(key, str) else key)
        # We'll encrypt the gzipped JSON bytes for compactness
        with open(json_gz_path, "rb") as gf:
            raw = gf.read()
        token = f.encrypt(raw)
        with open(json_enc_path, "wb") as out:
            out.write(token)
        print(f"Encrypted JSON backup written -> {json_enc_path}")
        print("NOTE: Keep the Fernet key safe. Without it you cannot decrypt the backup.")

    # Print brief preview
    print("\nSample records (first 5):")
    for r in rows[:5]:
        print(f" - {r['_id']} | {r.get('email')} | hash_present={'YES' if r.get('password_hash') else 'NO'}")

    print("\nBackup complete. Secure the backup files. Consider moving them to offline storage and deleting local copies when done.")

if __name__ == "__main__":
    main()