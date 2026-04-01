import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")


def seed_tools(cursor):
    sample_tools = [
        ("Cordless Drill", "TL-001", "Power Tools", "18V cordless drill", 8, 6, "100000000001"),
        ("Hammer", "TL-002", "Hand Tools", "Steel claw hammer", 15, 15, "100000000002"),
        ("Digital Multimeter", "TL-003", "Electrical", "True RMS multimeter", 10, 8, "100000000003"),
        ("Soldering Iron", "TL-004", "Electronics", "60W soldering iron", 12, 10, "100000000004"),
        ("Safety Goggles", "TL-005", "Safety", "Anti-fog protective goggles", 30, 29, "100000000005"),
        ("Adjustable Wrench", "TL-006", "Hand Tools", "10-inch adjustable wrench", 14, 13, "100000000006"),
    ]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for tool in sample_tools:
        tool_name, tool_code, category, description, quantity, available_quantity, barcode = tool
        status = "Available" if available_quantity > 0 else "Unavailable"

        cursor.execute("SELECT id FROM tools WHERE barcode = ?", (barcode,))
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO tools
                (tool_name, tool_code, category, description, quantity, available_quantity, barcode, status, date_added)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    tool_code,
                    category,
                    description,
                    quantity,
                    available_quantity,
                    barcode,
                    status,
                    now,
                ),
            )


def seed_borrowers(cursor):
    borrowers = [
        ("Alyssa Cruz", "STU-2026-001", "Computer Engineering", "09171234567"),
        ("Mark Dela Rosa", "STU-2026-002", "Mechanical Engineering", "09181234567"),
        ("Nina Lopez", "LAB-STAFF-01", "Laboratory", "09191234567"),
    ]

    for borrower in borrowers:
        cursor.execute("SELECT id FROM borrowers WHERE borrower_id = ?", (borrower[1],))
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO borrowers (borrower_name, borrower_id, course_department, contact_number)
                VALUES (?, ?, ?, ?)
                """,
                borrower,
            )


def seed_transactions(cursor):
    cursor.execute("SELECT COUNT(*) FROM transactions")
    count = cursor.fetchone()[0]
    if count > 0:
        return

    cursor.execute("SELECT id, barcode FROM tools ORDER BY id ASC")
    tools = cursor.fetchall()

    cursor.execute("SELECT id FROM borrowers ORDER BY id ASC")
    borrowers = cursor.fetchall()

    if len(tools) < 3 or len(borrowers) < 2:
        return

    today = datetime.now().date()
    tx_rows = [
        (
            borrowers[0][0],
            tools[0][0],
            tools[0][1],
            (today - timedelta(days=4)).strftime("%Y-%m-%d"),
            (today - timedelta(days=1)).strftime("%Y-%m-%d"),
            None,
            "borrowed",
        ),
        (
            borrowers[1][0],
            tools[2][0],
            tools[2][1],
            (today - timedelta(days=3)).strftime("%Y-%m-%d"),
            (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            None,
            "borrowed",
        ),
        (
            borrowers[2][0],
            tools[3][0],
            tools[3][1],
            (today - timedelta(days=10)).strftime("%Y-%m-%d"),
            (today - timedelta(days=6)).strftime("%Y-%m-%d"),
            (today - timedelta(days=5)).strftime("%Y-%m-%d 09:30:00"),
            "returned_overdue",
        ),
        (
            borrowers[0][0],
            tools[1][0],
            tools[1][1],
            (today - timedelta(days=2)).strftime("%Y-%m-%d"),
            (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            (today - timedelta(days=1)).strftime("%Y-%m-%d 13:15:00"),
            "returned",
        ),
    ]

    cursor.executemany(
        """
        INSERT INTO transactions
        (borrower_id, tool_id, barcode, borrow_date, expected_return_date, return_date, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        tx_rows,
    )


def sync_availability(cursor):
    cursor.execute("SELECT id, quantity FROM tools")
    tools = cursor.fetchall()

    for tool_id, quantity in tools:
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE tool_id = ? AND status = 'borrowed'",
            (tool_id,),
        )
        borrowed_count = cursor.fetchone()[0]
        available = max(0, quantity - borrowed_count)
        status = "Available" if available > 0 else "Unavailable"
        cursor.execute(
            "UPDATE tools SET available_quantity = ?, status = ? WHERE id = ?",
            (available, status, tool_id),
        )


def main():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    seed_tools(cursor)
    seed_borrowers(cursor)
    seed_transactions(cursor)
    sync_availability(cursor)

    conn.commit()
    conn.close()

    print("Sample data seeded successfully.")


if __name__ == "__main__":
    main()
