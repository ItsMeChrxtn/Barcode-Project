import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")


def init_database():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            tool_code TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL,
            description TEXT,
            quantity INTEGER NOT NULL DEFAULT 0,
            available_quantity INTEGER NOT NULL DEFAULT 0,
            barcode TEXT NOT NULL UNIQUE,
            barcode_image TEXT,
            tool_image TEXT,
            status TEXT NOT NULL DEFAULT 'Available',
            date_added TEXT NOT NULL
        )
        """
    )

    cursor.execute("PRAGMA table_info(tools)")
    tools_columns = {row[1] for row in cursor.fetchall()}
    if "barcode_image" not in tools_columns:
        cursor.execute("ALTER TABLE tools ADD COLUMN barcode_image TEXT")
    if "tool_image" not in tools_columns:
        cursor.execute("ALTER TABLE tools ADD COLUMN tool_image TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS borrowers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_name TEXT NOT NULL,
            borrower_id TEXT NOT NULL UNIQUE,
            course_department TEXT NOT NULL,
            contact_number TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            tool_id INTEGER NOT NULL,
            barcode TEXT NOT NULL,
            borrow_date TEXT NOT NULL,
            expected_return_date TEXT NOT NULL,
            return_date TEXT,
            lent_by_admin_id INTEGER,
            status TEXT NOT NULL,
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
            FOREIGN KEY (tool_id) REFERENCES tools(id),
            FOREIGN KEY (lent_by_admin_id) REFERENCES admins(id)
        )
        """
    )

    cursor.execute("PRAGMA table_info(admins)")
    admin_columns = {row[1] for row in cursor.fetchall()}
    if "first_name" not in admin_columns:
        cursor.execute("ALTER TABLE admins ADD COLUMN first_name TEXT DEFAULT ''")
        cursor.execute("UPDATE admins SET first_name = username WHERE COALESCE(first_name, '') = ''")
    if "last_name" not in admin_columns:
        cursor.execute("ALTER TABLE admins ADD COLUMN last_name TEXT DEFAULT ''")
        cursor.execute("UPDATE admins SET last_name = 'Admin' WHERE COALESCE(last_name, '') = ''")

    cursor.execute("PRAGMA table_info(transactions)")
    transaction_columns = {row[1] for row in cursor.fetchall()}
    if "lent_by_admin_id" not in transaction_columns:
        cursor.execute("ALTER TABLE transactions ADD COLUMN lent_by_admin_id INTEGER")

    cursor.execute("SELECT id FROM admins WHERE username = ?", ("admin",))
    admin_exists = cursor.fetchone()

    if not admin_exists:
        cursor.execute(
            "INSERT INTO admins (first_name, last_name, username, password_hash) VALUES (?, ?, ?, ?)",
            ("System", "Admin", "admin", generate_password_hash("admin123")),
        )
        print("Default admin created: username=admin, password=admin123")

    conn.commit()
    conn.close()
    print(f"Database initialized successfully at: {DATABASE_PATH}")


if __name__ == "__main__":
    init_database()
