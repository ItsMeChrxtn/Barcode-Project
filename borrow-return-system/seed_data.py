import os
import sqlite3
from datetime import datetime, timedelta
import barcode
from barcode.writer import ImageWriter

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")
BARCODE_DIR = os.path.join(BASE_DIR, "static", "barcodes")


def create_barcode_image(barcode_value):
    os.makedirs(BARCODE_DIR, exist_ok=True)
    file_stem = f"barcode_{barcode_value}"
    path_without_ext = os.path.join(BARCODE_DIR, file_stem)
    code128 = barcode.get("code128", barcode_value, writer=ImageWriter())
    generated_path = code128.save(path_without_ext)
    return os.path.basename(generated_path)


def seed_tools(cursor):
    sample_tools = [
        ("Cordless Drill", "TL-001", "Power Tools", "18V cordless drill", 8, 6, "100000000001"),
        ("Hammer", "TL-002", "Hand Tools", "Steel claw hammer", 15, 15, "100000000002"),
        ("Digital Multimeter", "TL-003", "Electrical", "True RMS multimeter", 10, 8, "100000000003"),
        ("Soldering Iron", "TL-004", "Electronics", "60W soldering iron", 12, 10, "100000000004"),
        ("Safety Goggles", "TL-005", "Safety", "Anti-fog protective goggles", 30, 29, "100000000005"),
        ("Adjustable Wrench", "TL-006", "Hand Tools", "10-inch adjustable wrench", 14, 13, "100000000006"),
        ("Needle Nose Pliers", "TL-007", "Hand Tools", "Long reach pliers for precision grip", 16, 16, "100000000007"),
        ("Flat Screwdriver", "TL-008", "Hand Tools", "Flat head screwdriver set", 20, 18, "100000000008"),
        ("Phillips Screwdriver", "TL-009", "Hand Tools", "Phillips screwdriver set", 20, 17, "100000000009"),
        ("Impact Driver", "TL-010", "Power Tools", "Heavy-duty impact driver", 7, 5, "100000000010"),
        ("Bench Grinder", "TL-011", "Power Tools", "Dual wheel bench grinder", 4, 4, "100000000011"),
        ("Heat Gun", "TL-012", "Electronics", "Variable temperature heat gun", 6, 5, "100000000012"),
        ("Extension Cord", "TL-013", "Electrical", "10-meter heavy duty extension cord", 18, 15, "100000000013"),
        ("Clamp Meter", "TL-014", "Electrical", "Digital clamp meter", 9, 9, "100000000014"),
        ("Wire Stripper", "TL-015", "Electrical", "Automatic wire stripping tool", 13, 11, "100000000015"),
        ("Breadboard Kit", "TL-016", "Electronics", "Reusable prototyping breadboard kit", 22, 20, "100000000016"),
        ("Oscilloscope Probe", "TL-017", "Electronics", "100MHz oscilloscope probe", 11, 10, "100000000017"),
        ("Face Shield", "TL-018", "Safety", "Clear impact face shield", 14, 14, "100000000018"),
        ("Protective Gloves", "TL-019", "Safety", "Cut-resistant gloves pair", 25, 22, "100000000019"),
        ("Tape Measure", "TL-020", "Measuring Tools", "5-meter tape measure", 19, 19, "100000000020"),
        ("Digital Caliper", "TL-021", "Measuring Tools", "Stainless digital caliper", 8, 7, "100000000021"),
        ("Utility Knife", "TL-022", "Cutting Tools", "Retractable utility knife", 17, 16, "100000000022"),
        ("Pipe Cutter", "TL-023", "Cutting Tools", "PVC and copper pipe cutter", 7, 7, "100000000023"),
        ("Rivet Gun", "TL-024", "Fastening Tools", "Manual rivet installation gun", 6, 5, "100000000024"),
        ("Torque Wrench", "TL-025", "Fastening Tools", "Adjustable torque wrench", 5, 4, "100000000025"),
        ("Pipe Wrench", "TL-026", "Plumbing", "14-inch pipe wrench", 9, 8, "100000000026"),
        ("Plunger Pump", "TL-027", "Plumbing", "Drain unclogging plunger", 10, 10, "100000000027"),
        ("Label Maker", "TL-028", "Other", "Portable label printer", 4, 4, "100000000028"),
        ("Toolbox Cart", "TL-029", "Other", "Rolling toolbox cart", 3, 3, "100000000029"),
        ("Laser Level", "TL-030", "Measuring Tools", "Self-leveling laser guide", 5, 4, "100000000030"),
    ]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for tool in sample_tools:
        tool_name, tool_code, category, description, quantity, available_quantity, barcode = tool
        status = "Available" if available_quantity > 0 else "Unavailable"
        barcode_image = create_barcode_image(barcode)

        cursor.execute("SELECT id FROM tools WHERE barcode = ?", (barcode,))
        if cursor.fetchone() is None:
            cursor.execute(
                """
                INSERT INTO tools
                (tool_name, tool_code, category, description, quantity, available_quantity, barcode, barcode_image, status, date_added)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    tool_code,
                    category,
                    description,
                    quantity,
                    available_quantity,
                    barcode,
                    barcode_image,
                    status,
                    now,
                ),
            )
        else:
            cursor.execute(
                "UPDATE tools SET barcode_image = COALESCE(barcode_image, ?) WHERE barcode = ?",
                (barcode_image, barcode),
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
