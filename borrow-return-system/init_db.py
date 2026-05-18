import os
from pymongo import MongoClient
from werkzeug.security import generate_password_hash


def init_database():
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    client = MongoClient(uri)
    db_name = os.environ.get("MONGODB_DB", "borrow_return_db")
    db = client[db_name]

    db.admins.create_index("username", unique=True)
    db.tools.create_index("tool_code", unique=True)
    db.tools.create_index("barcode", unique=True)
    db.borrowers.create_index("borrower_id", unique=True)

    if db.admins.find_one({"username": "admin"}) is None:
        db.admins.insert_one({
            "first_name": "System",
            "last_name": "Admin",
            "username": "admin",
            "password_hash": generate_password_hash("admin123"),
        })
        print("Default admin created: username=admin, password=admin123")
    else:
        print("Default admin already exists.")

    client.close()
    print("MongoDB initialisation complete.")


if __name__ == "__main__":
    init_database()
