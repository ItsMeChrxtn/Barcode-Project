import csv
import os
import random
import sqlite3
import uuid
from datetime import datetime, date
from functools import wraps
from io import StringIO

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
import barcode
from barcode.writer import ImageWriter
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")
BARCODE_DIR = os.path.join(BASE_DIR, "static", "barcodes")
TOOL_IMAGE_DIR = os.path.join(BASE_DIR, "static", "tool_images")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
TOOL_CODE_PREFIX = "TL-"
CATEGORY_OPTIONS = [
    "Hand Tools",
    "Power Tools",
    "Electrical",
    "Electronics",
    "Safety",
    "Measuring Tools",
    "Cutting Tools",
    "Fastening Tools",
    "Plumbing",
    "Other",
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "replace-this-in-production")
app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"


def parse_cors_origins(raw_origins):
    if not raw_origins:
        return []
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


cors_origins = parse_cors_origins(os.environ.get("CORS_ALLOWED_ORIGINS", ""))
if cors_origins:
    CORS(app, resources={r"/api/*": {"origins": cors_origins}}, supports_credentials=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        ensure_schema(g.db)
    return g.db


def ensure_schema(db):
    # Keep backward compatibility for existing local databases.
    tools_columns = db.execute("PRAGMA table_info(tools)").fetchall()
    column_names = {row["name"] for row in tools_columns}
    if "barcode_image" not in column_names:
        db.execute("ALTER TABLE tools ADD COLUMN barcode_image TEXT")
        db.commit()
    if "tool_image" not in column_names:
        db.execute("ALTER TABLE tools ADD COLUMN tool_image TEXT")
        db.commit()

    admins_columns = db.execute("PRAGMA table_info(admins)").fetchall()
    admin_column_names = {row["name"] for row in admins_columns}
    if "first_name" not in admin_column_names:
        db.execute("ALTER TABLE admins ADD COLUMN first_name TEXT DEFAULT ''")
        db.execute("UPDATE admins SET first_name = username WHERE COALESCE(first_name, '') = ''")
        db.commit()
    if "last_name" not in admin_column_names:
        db.execute("ALTER TABLE admins ADD COLUMN last_name TEXT DEFAULT ''")
        db.execute("UPDATE admins SET last_name = 'Admin' WHERE COALESCE(last_name, '') = ''")
        db.commit()

    transactions_columns = db.execute("PRAGMA table_info(transactions)").fetchall()
    transaction_column_names = {row["name"] for row in transactions_columns}
    if "lent_by_admin_id" not in transaction_column_names:
        db.execute("ALTER TABLE transactions ADD COLUMN lent_by_admin_id INTEGER")
        db.commit()


@app.teardown_appcontext
def close_db(error=None):
    _ = error
    db = g.pop("db", None)
    if db is not None:
        db.close()


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if session.get("admin_id") is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def normalize_tool_status(tool_row):
    return "Available" if tool_row["available_quantity"] > 0 else "Unavailable"


def update_tool_status(db, tool_id):
    tool = db.execute("SELECT id, quantity, available_quantity FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if not tool:
        return
    available_qty = max(0, min(tool["available_quantity"], tool["quantity"]))
    status = "Available" if available_qty > 0 else "Unavailable"
    db.execute(
        "UPDATE tools SET available_quantity = ?, status = ? WHERE id = ?",
        (available_qty, status, tool_id),
    )


def parse_date_input(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def generate_next_tool_code(db):
    tool_codes = db.execute(
        "SELECT tool_code FROM tools WHERE tool_code LIKE ?",
        (f"{TOOL_CODE_PREFIX}%",),
    ).fetchall()

    max_number = -1
    for row in tool_codes:
        suffix = row["tool_code"][len(TOOL_CODE_PREFIX) :]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))

    return f"{TOOL_CODE_PREFIX}{max_number + 1:03d}"


def get_next_tool_number(db):
    tool_codes = db.execute(
        "SELECT tool_code FROM tools WHERE tool_code LIKE ?",
        (f"{TOOL_CODE_PREFIX}%",),
    ).fetchall()

    max_number = -1
    for row in tool_codes:
        suffix = row["tool_code"][len(TOOL_CODE_PREFIX) :]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))

    return max_number + 1


def format_tool_code(number):
    return f"{TOOL_CODE_PREFIX}{number:03d}"


def get_category_options(selected_category=None):
    options = list(CATEGORY_OPTIONS)
    if selected_category and selected_category not in options:
        options.append(selected_category)
    return options


def render_add_tool_page(db, generated_tool=None, form_data=None):
    return render_template(
        "add_tool.html",
        generated_tool=generated_tool,
        next_tool_code=generate_next_tool_code(db),
        category_options=get_category_options((form_data or {}).get("category")),
        form_data=form_data or {},
    )


def render_admins_page(db, form_data=None):
    admins = db.execute(
        "SELECT id, username, first_name, last_name FROM admins ORDER BY username ASC"
    ).fetchall()
    return render_template(
        "admins.html",
        admins=admins,
        form_data=form_data or {},
    )


def get_tool_by_barcode(db, barcode_value):
    return db.execute(
        """
        SELECT id, tool_name, tool_code, category, description, quantity,
               available_quantity, barcode, barcode_image, tool_image, status
        FROM tools
        WHERE barcode = ?
        """,
        (barcode_value.strip(),),
    ).fetchone()


def get_active_borrow_transaction(db, barcode_value):
    return db.execute(
        """
        SELECT t.id,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status,
               b.borrower_name,
               b.borrower_id,
               b.course_department,
               b.contact_number,
               tl.id AS tool_id,
               tl.tool_name,
               tl.tool_code,
               tl.category,
             t.barcode,
             TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
         LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        WHERE t.barcode = ? AND t.status = 'borrowed'
        ORDER BY t.borrow_date ASC, t.id ASC
        LIMIT 1
        """,
        (barcode_value.strip(),),
    ).fetchone()


def upsert_borrower(db, borrower_name, borrower_code, course_department, contact_number):
    borrower = db.execute(
        "SELECT id FROM borrowers WHERE borrower_id = ?",
        (borrower_code,),
    ).fetchone()

    if borrower is None:
        cursor = db.execute(
            """
            INSERT INTO borrowers (borrower_name, borrower_id, course_department, contact_number)
            VALUES (?, ?, ?, ?)
            """,
            (borrower_name, borrower_code, course_department, contact_number),
        )
        return cursor.lastrowid

    borrower_id = borrower["id"]
    db.execute(
        """
        UPDATE borrowers
        SET borrower_name = ?, course_department = ?, contact_number = ?
        WHERE id = ?
        """,
        (borrower_name, course_department, contact_number, borrower_id),
    )
    return borrower_id


def build_tool_payload(tool):
    return {
        "id": tool["id"],
        "tool_name": tool["tool_name"],
        "tool_code": tool["tool_code"],
        "category": tool["category"],
        "quantity": tool["quantity"],
        "available_quantity": tool["available_quantity"],
        "barcode": tool["barcode"],
        "barcode_image": tool["barcode_image"],
        "tool_image": tool["tool_image"],
        "status": normalize_tool_status(tool),
    }


def build_transaction_payload(transaction):
    return {
        "id": transaction["id"],
        "borrow_date": transaction["borrow_date"],
        "expected_return_date": transaction["expected_return_date"],
        "return_date": transaction["return_date"],
        "status": transaction["status"],
        "borrower_name": transaction["borrower_name"],
        "borrower_id": transaction["borrower_id"],
        "course_department": transaction["course_department"],
        "contact_number": transaction["contact_number"],
        "tool_id": transaction["tool_id"],
        "tool_name": transaction["tool_name"],
        "tool_code": transaction["tool_code"],
        "category": transaction["category"],
        "barcode": transaction["barcode"],
        "lent_by_admin_name": transaction["lent_by_admin_name"],
    }


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def get_project_profiles():
    return [
        {
            "name": "BERTOLDO, Restygie D.",
            "role": "Proponent",
            "image": "BERTOLDO, Restygie D..jpg",
        },
        {
            "name": "CASTUERAS, Rhenard R.",
            "role": "Proponent",
            "image": "CASTUERAS, Rhenard R..jpg",
        },
        {
            "name": "VEDAD, Kim Jay C.",
            "role": "Proponent",
            "image": "VEDAD, Kim Jay C..jpg",
        },
        {
            "name": "Nicky Jay R. Evangelista",
            "role": "Adviser",
            "image": "Nicky Jay R. Evangelista - Adviser.jpg",
        },
        {
            "name": "Diane P. Arayata",
            "role": "Technical Critic",
            "image": "Diane P. Arayata - Technical critic.jpg",
        },
    ]


def process_borrow_scan(db, payload):
    barcode_value = payload.get("barcode", "").strip()
    borrower_name = payload.get("borrower_name", "").strip()
    borrower_code = payload.get("borrower_id", "").strip()
    course_department = payload.get("course_department", "").strip()
    contact_number = payload.get("contact_number", "").strip()

    if not all([borrower_name, borrower_code, course_department, contact_number]):
        return {"ok": False, "message": "Please complete the borrower information before scanning.", "category": "warning"}, 400

    tool = get_tool_by_barcode(db, barcode_value)
    if tool is None:
        return {"ok": False, "message": "No tool found for the scanned barcode.", "category": "error"}, 404

    active_transaction = get_active_borrow_transaction(db, barcode_value)
    if active_transaction is not None:
        return {
            "ok": False,
            "message": "This barcode is already borrowed.",
            "category": "warning",
            "tool": build_tool_payload(tool),
            "transaction": build_transaction_payload(active_transaction),
        }, 409

    if tool["available_quantity"] <= 0:
        return {
            "ok": False,
            "message": "This tool is currently unavailable.",
            "category": "warning",
            "tool": build_tool_payload(tool),
        }, 409

    borrower_id = upsert_borrower(
        db,
        borrower_name,
        borrower_code,
        course_department,
        contact_number,
    )
    borrow_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lending_admin_id = session.get("admin_id")

    cursor = db.execute(
        """
        INSERT INTO transactions
        (borrower_id, tool_id, barcode, borrow_date, expected_return_date, return_date, status, lent_by_admin_id)
        VALUES (?, ?, ?, ?, ?, NULL, 'borrowed', ?)
        """,
        (borrower_id, tool["id"], barcode_value, borrow_timestamp, "", lending_admin_id),
    )
    db.execute(
        "UPDATE tools SET available_quantity = available_quantity - 1 WHERE id = ?",
        (tool["id"],),
    )
    update_tool_status(db, tool["id"])
    db.commit()

    updated_tool = get_tool_by_barcode(db, barcode_value)
    saved_transaction = db.execute(
        """
        SELECT t.id,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status,
               b.borrower_name,
               b.borrower_id,
               b.course_department,
               b.contact_number,
               tl.id AS tool_id,
               tl.tool_name,
               tl.tool_code,
               tl.category,
             t.barcode,
             TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
         LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        WHERE t.id = ?
        """,
        (cursor.lastrowid,),
    ).fetchone()

    return {
        "ok": True,
        "action": "borrowed",
        "message": "Borrow record saved successfully.",
        "category": "success",
        "tool": build_tool_payload(updated_tool),
        "transaction": build_transaction_payload(saved_transaction),
    }, 200


def process_return_scan(db, payload):
    barcode_value = payload.get("barcode", "").strip()
    tool = get_tool_by_barcode(db, barcode_value)

    if tool is None:
        return {"ok": False, "message": "No tool found for the scanned barcode.", "category": "error"}, 404

    active_transaction = get_active_borrow_transaction(db, barcode_value)
    if active_transaction is None:
        return {
            "ok": False,
            "message": "This barcode is not currently borrowed.",
            "category": "warning",
            "tool": build_tool_payload(tool),
        }, 409

    returned_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        UPDATE transactions
        SET return_date = ?, status = 'returned'
        WHERE id = ?
        """,
        (returned_at, active_transaction["id"]),
    )
    db.execute(
        "UPDATE tools SET available_quantity = available_quantity + 1 WHERE id = ?",
        (active_transaction["tool_id"],),
    )
    update_tool_status(db, active_transaction["tool_id"])
    db.commit()

    updated_tool = get_tool_by_barcode(db, barcode_value)
    saved_transaction = db.execute(
        """
        SELECT t.id,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status,
               b.borrower_name,
               b.borrower_id,
               b.course_department,
               b.contact_number,
               tl.id AS tool_id,
               tl.tool_name,
               tl.tool_code,
               tl.category,
             t.barcode,
             TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
         LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        WHERE t.id = ?
        """,
        (active_transaction["id"],),
    ).fetchone()

    return {
        "ok": True,
        "action": "returned",
        "message": "Return record saved successfully.",
        "category": "success",
        "tool": build_tool_payload(updated_tool),
        "transaction": build_transaction_payload(saved_transaction),
    }, 200


def generate_unique_barcode(db, length=12):
    while True:
        barcode_value = "".join(str(random.randint(0, 9)) for _ in range(length))
        exists = db.execute("SELECT id FROM tools WHERE barcode = ?", (barcode_value,)).fetchone()
        if not exists:
            return barcode_value


def create_barcode_image(barcode_value):
    os.makedirs(BARCODE_DIR, exist_ok=True)
    file_stem = f"barcode_{barcode_value}"
    path_without_ext = os.path.join(BARCODE_DIR, file_stem)

    code128 = barcode.get("code128", barcode_value, writer=ImageWriter())
    generated_path = code128.save(path_without_ext)
    return os.path.basename(generated_path)


def save_tool_image(file_storage):
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return None

    filename = secure_filename(file_storage.filename)
    if not filename or "." not in filename:
        return None

    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in {"png", "jpg", "jpeg", "webp"}:
        return None

    os.makedirs(TOOL_IMAGE_DIR, exist_ok=True)
    generated_name = f"tool_{uuid.uuid4().hex[:12]}.{extension}"
    save_path = os.path.join(TOOL_IMAGE_DIR, generated_name)
    file_storage.save(save_path)
    return generated_name


def parse_tool_ids(raw_ids):
    parsed_ids = []
    seen_ids = set()

    for raw_id in raw_ids:
        try:
            tool_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        if tool_id in seen_ids:
            continue

        parsed_ids.append(tool_id)
        seen_ids.add(tool_id)

    return parsed_ids


def split_deletable_tool_ids(db, tool_ids):
    if not tool_ids:
        return [], []

    placeholders = ",".join("?" for _ in tool_ids)
    rows = db.execute(
        f"""
        SELECT t.id, t.tool_name,
               EXISTS(
                   SELECT 1
                   FROM transactions tr
                   WHERE tr.tool_id = t.id AND tr.status = 'borrowed'
               ) AS is_borrowed
        FROM tools t
        WHERE t.id IN ({placeholders})
        """,
        tool_ids,
    ).fetchall()

    borrowed_ids = {row["id"] for row in rows if row["is_borrowed"]}
    deletable_ids = [tool_id for tool_id in tool_ids if tool_id not in borrowed_ids]
    blocked_tools = [row for row in rows if row["is_borrowed"]]
    return deletable_ids, blocked_tools


def build_tool_filters(search, category, availability):
    where_clauses = ["1 = 1"]
    params = []

    if search:
        where_clauses.append(
            """
            (
                tool_name LIKE ?
                OR tool_code LIKE ?
                OR barcode LIKE ?
                OR category LIKE ?
                OR status LIKE ?
            )
            """
        )
        wildcard = f"%{search}%"
        params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

    if category:
        where_clauses.append("category = ?")
        params.append(category)

    if availability == "available":
        where_clauses.append("available_quantity > 0")
    elif availability == "unavailable":
        where_clauses.append("available_quantity <= 0")

    return " AND ".join(where_clauses), params


@app.route("/")
def index():
    return render_template("landing.html", profiles=get_project_profiles())


@app.route("/title-page")
def title_page():
    return render_template("landing.html", profiles=get_project_profiles())


@app.route("/template-image/<path:filename>")
def template_image(filename):
    return send_from_directory(TEMPLATE_DIR, filename)


@app.route("/healthz")
def healthz():
    return {"ok": True, "service": "borrow-return-system"}, 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html")

        db = get_db()
        admin = db.execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()

        if admin is None or not check_password_hash(admin["password_hash"], password):
            flash("Invalid username or password.", "danger")
            return render_template("login.html")

        session.clear()
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]
        session["admin_full_name"] = f"{admin['first_name']} {admin['last_name']}".strip()
        flash("Welcome back!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/admins", methods=["GET", "POST"])
@login_required
def admins():
    db = get_db()

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        form_data = {
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
        }

        if not first_name or not last_name or not username or not password or not confirm_password:
            flash("First name, last name, username, password, and confirmation are required.", "danger")
            return render_admins_page(db, form_data=form_data)

        if len(first_name) < 2 or len(last_name) < 2:
            flash("First name and last name must be at least 2 characters long.", "danger")
            return render_admins_page(db, form_data=form_data)

        if len(username) < 3:
            flash("Username must be at least 3 characters long.", "danger")
            return render_admins_page(db, form_data=form_data)

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_admins_page(db, form_data=form_data)

        if password != confirm_password:
            flash("Password confirmation does not match.", "danger")
            return render_admins_page(db, form_data=form_data)

        duplicate_admin = db.execute(
            "SELECT id FROM admins WHERE username = ?",
            (username,),
        ).fetchone()
        if duplicate_admin is not None:
            flash("That username is already in use.", "danger")
            return render_admins_page(db, form_data=form_data)

        db.execute(
            "INSERT INTO admins (first_name, last_name, username, password_hash) VALUES (?, ?, ?, ?)",
            (first_name, last_name, username, generate_password_hash(password)),
        )
        db.commit()
        flash("New admin account created successfully.", "success")
        return redirect(url_for("admins"))

    return render_admins_page(db)


@app.route("/admins/<int:admin_id>/edit", methods=["GET", "POST"])
@login_required
def edit_admin(admin_id):
    current_admin_id = session.get("admin_id")
    if current_admin_id != admin_id:
        flash("You can only edit your own account details.", "warning")
        return redirect(url_for("edit_admin", admin_id=current_admin_id))

    db = get_db()
    admin = db.execute(
        "SELECT id, first_name, last_name, username FROM admins WHERE id = ?",
        (admin_id,),
    ).fetchone()

    if admin is None:
        flash("Admin account not found.", "danger")
        return redirect(url_for("admins"))

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        username = request.form.get("username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        form_admin = {
            "id": admin_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
        }

        if not first_name or not last_name or not username:
            flash("First name, last name, and username are required.", "danger")
            return render_template("admin_edit.html", admin=form_admin)

        if len(first_name) < 2 or len(last_name) < 2:
            flash("First name and last name must be at least 2 characters long.", "danger")
            return render_template("admin_edit.html", admin=form_admin)

        if len(username) < 3:
            flash("Username must be at least 3 characters long.", "danger")
            return render_template("admin_edit.html", admin=form_admin)

        duplicate_admin = db.execute(
            "SELECT id FROM admins WHERE username = ? AND id != ?",
            (username, admin_id),
        ).fetchone()
        if duplicate_admin is not None:
            flash("That username is already in use.", "danger")
            return render_template("admin_edit.html", admin=form_admin)

        if new_password or confirm_password:
            if len(new_password) < 6:
                flash("New password must be at least 6 characters long.", "danger")
                return render_template("admin_edit.html", admin=form_admin)
            if new_password != confirm_password:
                flash("Password confirmation does not match.", "danger")
                return render_template("admin_edit.html", admin=form_admin)

            db.execute(
                """
                UPDATE admins
                SET first_name = ?, last_name = ?, username = ?, password_hash = ?
                WHERE id = ?
                """,
                (first_name, last_name, username, generate_password_hash(new_password), admin_id),
            )
        else:
            db.execute(
                """
                UPDATE admins
                SET first_name = ?, last_name = ?, username = ?
                WHERE id = ?
                """,
                (first_name, last_name, username, admin_id),
            )

        db.commit()
        session["admin_username"] = username
        session["admin_full_name"] = f"{first_name} {last_name}".strip()
        flash("Your account details were updated successfully.", "success")
        return redirect(url_for("admins"))

    return render_template("admin_edit.html", admin=admin)


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()

    total_tools = db.execute("SELECT COUNT(*) AS total FROM tools").fetchone()["total"]
    available_tools = db.execute(
        "SELECT COUNT(*) AS total FROM tools WHERE available_quantity > 0"
    ).fetchone()["total"]
    borrowed_tools = db.execute(
        "SELECT COUNT(*) AS total FROM transactions WHERE status = 'borrowed'"
    ).fetchone()["total"]
    returned_today = db.execute(
        "SELECT COUNT(*) AS total FROM transactions WHERE DATE(return_date) = ?",
        (date.today().isoformat(),),
    ).fetchone()["total"]
    total_transactions = db.execute("SELECT COUNT(*) AS total FROM transactions").fetchone()["total"]
    total_admins = db.execute("SELECT COUNT(*) AS total FROM admins").fetchone()["total"]

    recent_transactions = db.execute(
        """
        SELECT t.id,
               b.borrower_name,
               b.borrower_id,
               tl.tool_name,
               t.barcode,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
        ORDER BY t.id DESC
        LIMIT 10
        """
    ).fetchall()

    return render_template(
        "dashboard.html",
        total_tools=total_tools,
        available_tools=available_tools,
        borrowed_tools=borrowed_tools,
        returned_today=returned_today,
        total_transactions=total_transactions,
        total_admins=total_admins,
        recent_transactions=recent_transactions,
    )


@app.route("/tools")
@login_required
def tools():
    db = get_db()
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    availability = request.args.get("availability", "").strip()

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    per_page = 9
    where_sql, params = build_tool_filters(search, category, availability)
    total_items = db.execute(
        f"SELECT COUNT(*) AS total FROM tools WHERE {where_sql}",
        params,
    ).fetchone()["total"]
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    page = min(page, total_pages)
    offset = (page - 1) * per_page

    query = f"""
        SELECT id, tool_name, tool_code, category, description, quantity,
               available_quantity, barcode, barcode_image, status, date_added, tool_image
        FROM tools
        WHERE {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """
    tool_rows = db.execute(query, [*params, per_page, offset]).fetchall()
    categories = db.execute("SELECT DISTINCT category FROM tools ORDER BY category").fetchall()

    return render_template(
        "tools.html",
        tools=tool_rows,
        categories=categories,
        category_options=CATEGORY_OPTIONS,
        search=search,
        selected_category=category,
        availability=availability,
        next_tool_code=generate_next_tool_code(db),
        page=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
    )


@app.route("/tools/barcodes/print-selected", methods=["POST"])
@login_required
def print_selected_barcodes():
    db = get_db()
    valid_ids = parse_tool_ids(request.form.getlist("tool_ids"))

    if not valid_ids:
        flash("Select at least one tool barcode to print.", "warning")
        return redirect(url_for("tools"))

    placeholders = ",".join("?" for _ in valid_ids)
    rows = db.execute(
        f"""
        SELECT id, tool_name, tool_code, category, barcode, barcode_image
        FROM tools
        WHERE id IN ({placeholders})
        ORDER BY id DESC
        """,
        valid_ids,
    ).fetchall()

    return render_template("print_barcodes.html", tools=rows, print_title="Selected Tool Barcodes")


@app.route("/tools/barcodes/print-all")
@login_required
def print_all_barcodes():
    db = get_db()
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    availability = request.args.get("availability", "").strip()
    where_sql, params = build_tool_filters(search, category, availability)

    rows = db.execute(
        f"""
        SELECT id, tool_name, tool_code, category, barcode, barcode_image
        FROM tools
        WHERE {where_sql}
        ORDER BY id DESC
        """,
        params,
    ).fetchall()

    if not rows:
        flash("No tool barcodes available to print for the current filter.", "warning")
        return redirect(url_for("tools", search=search, category=category, availability=availability))

    return render_template("print_barcodes.html", tools=rows, print_title="All Tool Barcodes")


@app.route("/tools/add", methods=["GET", "POST"])
@login_required
def add_tool():
    db = get_db()

    if request.method == "POST":
        tool_name = request.form.get("tool_name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        quantity_text = request.form.get("quantity", "0").strip()
        uploaded_tool_image = save_tool_image(request.files.get("tool_image"))
        if not all([tool_name, category]):
            flash("Tool name and category are required.", "danger")
            return redirect(url_for("tools"))

        if category not in CATEGORY_OPTIONS:
            flash("Please select a valid category.", "danger")
            return redirect(url_for("tools"))

        try:
            quantity = int(quantity_text)
            if quantity < 1:
                raise ValueError
        except ValueError:
            flash("Quantity must be at least 1.", "danger")
            return redirect(url_for("tools"))

        start_number = get_next_tool_number(db)
        created_codes = []
        created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for offset in range(quantity):
            tool_code = format_tool_code(start_number + offset)
            barcode = generate_unique_barcode(db)
            barcode_image = create_barcode_image(barcode)
            db.execute(
                """
                INSERT INTO tools
                (tool_name, tool_code, category, description, quantity, available_quantity, barcode, barcode_image, tool_image, status, date_added)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    tool_code,
                    category,
                    description,
                    1,
                    1,
                    barcode,
                    barcode_image,
                    uploaded_tool_image,
                    "Available",
                    created_time,
                ),
            )
            created_codes.append(tool_code)

        db.commit()

        flash(
            f"Created {quantity} tool unit(s): {created_codes[0]} to {created_codes[-1]}.",
            "success",
        )
        return redirect(url_for("tools"))

    return redirect(url_for("tools"))


@app.route("/tools/<int:tool_id>/edit", methods=["GET", "POST"])
@login_required
def edit_tool(tool_id):
    db = get_db()
    tool = db.execute("SELECT * FROM tools WHERE id = ?", (tool_id,)).fetchone()

    if tool is None:
        flash("Tool not found.", "danger")
        return redirect(url_for("tools"))

    if request.method == "POST":
        tool_name = request.form.get("tool_name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        quantity_text = request.form.get("quantity", "0").strip()
        barcode = request.form.get("barcode", "").strip()
        tool_code = tool["tool_code"]
        form_tool = dict(tool)
        form_tool.update(
            {
                "tool_name": tool_name,
                "category": category,
                "description": description,
                "quantity": quantity_text,
                "barcode": barcode,
            }
        )

        if not all([tool_name, category, barcode]):
            flash("Tool name, category, and barcode are required.", "danger")
            return render_template(
                "edit_tool.html",
                tool=form_tool,
                category_options=get_category_options(category),
            )

        if category not in get_category_options(tool["category"]):
            flash("Please select a valid category.", "danger")
            return render_template(
                "edit_tool.html",
                tool=form_tool,
                category_options=get_category_options(category),
            )

        try:
            quantity = int(quantity_text)
            if quantity < 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a non-negative number.", "danger")
            return render_template(
                "edit_tool.html",
                tool=form_tool,
                category_options=get_category_options(category),
            )

        duplicate_barcode = db.execute(
            "SELECT id FROM tools WHERE barcode = ? AND id != ?",
            (barcode, tool_id),
        ).fetchone()
        if duplicate_barcode:
            flash("Barcode already exists. Please use a unique barcode.", "danger")
            return render_template(
                "edit_tool.html",
                tool=form_tool,
                category_options=get_category_options(category),
            )

        borrowed_count = db.execute(
            "SELECT COUNT(*) AS total FROM transactions WHERE tool_id = ? AND status = 'borrowed'",
            (tool_id,),
        ).fetchone()["total"]

        if quantity < borrowed_count:
            flash(
                "Quantity cannot be less than currently borrowed units.",
                "danger",
            )
            return render_template(
                "edit_tool.html",
                tool=form_tool,
                category_options=get_category_options(category),
            )

        available_quantity = max(0, quantity - borrowed_count)
        status = "Available" if available_quantity > 0 else "Unavailable"
        barcode_image = tool["barcode_image"]
        if tool["barcode"] != barcode or not barcode_image:
            barcode_image = create_barcode_image(barcode)

        db.execute(
            """
            UPDATE tools
            SET tool_name = ?, tool_code = ?, category = ?, description = ?,
                quantity = ?, available_quantity = ?, barcode = ?, barcode_image = ?, status = ?
            WHERE id = ?
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
                tool_id,
            ),
        )
        db.commit()

        flash("Tool updated successfully.", "success")
        return redirect(url_for("tools"))

    return render_template(
        "edit_tool.html",
        tool=tool,
        category_options=get_category_options(tool["category"]),
    )


@app.route("/tools/<int:tool_id>/delete", methods=["POST"])
@login_required
def delete_tool(tool_id):
    db = get_db()
    deletable_ids, blocked_tools = split_deletable_tool_ids(db, [tool_id])
    if blocked_tools:
        flash("Cannot delete tool while it is currently borrowed.", "danger")
        return redirect(url_for("tools"))

    if not deletable_ids:
        flash("Tool not found.", "warning")
        return redirect(url_for("tools"))

    db.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    db.commit()

    flash("Tool deleted successfully.", "info")
    return redirect(url_for("tools"))


@app.route("/tools/delete-selected", methods=["POST"])
@login_required
def delete_selected_tools():
    db = get_db()
    selected_ids = parse_tool_ids(request.form.getlist("tool_ids"))

    if not selected_ids:
        flash("Select at least one tool to delete.", "warning")
        return redirect(url_for("tools"))

    deletable_ids, blocked_tools = split_deletable_tool_ids(db, selected_ids)

    if deletable_ids:
        placeholders = ",".join("?" for _ in deletable_ids)
        db.execute(f"DELETE FROM tools WHERE id IN ({placeholders})", deletable_ids)
        db.commit()
        flash(f"Deleted {len(deletable_ids)} tool(s) successfully.", "info")

    if blocked_tools:
        blocked_names = ", ".join(row["tool_name"] for row in blocked_tools[:3])
        if len(blocked_tools) > 3:
            blocked_names += ", ..."
        flash(
            f"{len(blocked_tools)} tool(s) not deleted because they are currently borrowed: {blocked_names}",
            "warning",
        )

    if not deletable_ids and not blocked_tools:
        flash("No matching tools were found to delete.", "warning")

    return redirect(url_for("tools"))


@app.route("/tools/<int:tool_id>/barcode/regenerate", methods=["POST"])
@login_required
def regenerate_tool_barcode(tool_id):
    db = get_db()
    tool = db.execute("SELECT id, barcode FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if tool is None:
        flash("Tool not found.", "danger")
        return redirect(url_for("tools"))

    barcode_image = create_barcode_image(tool["barcode"])
    db.execute(
        "UPDATE tools SET barcode_image = ? WHERE id = ?",
        (barcode_image, tool_id),
    )
    db.commit()

    flash("Barcode image generated successfully.", "success")
    return redirect(url_for("tools"))


@app.route("/borrow", methods=["GET"])
@login_required
def borrow_tool():
    return render_template("borrow.html")


@app.route("/return", methods=["GET"])
@login_required
def return_tool():
    return redirect(url_for("borrow_tool"))


@app.route("/api/scan/process", methods=["POST"])
@login_required
def api_process_scan():
    payload = request.get_json(silent=True) or request.form.to_dict()
    mode = payload.get("mode", "borrow").strip().lower()
    barcode_value = payload.get("barcode", "").strip()

    if mode not in {"borrow", "return"}:
        return {"ok": False, "message": "Invalid scan mode.", "category": "error"}, 400

    if not barcode_value:
        return {"ok": False, "message": "Please scan a barcode first.", "category": "warning"}, 400

    db = get_db()
    if mode == "borrow":
        return process_borrow_scan(db, payload)
    return process_return_scan(db, payload)


@app.route("/transactions")
@login_required
def transactions():
    db = get_db()

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip()
    borrower = request.args.get("borrower", "").strip()
    tool = request.args.get("tool", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    query = """
        SELECT t.id,
               b.borrower_name,
               b.borrower_id,
               tl.tool_name,
               t.barcode,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status,
               TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
        LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        WHERE 1 = 1
    """
    params = []

    if search:
        query += """
            AND (
                b.borrower_name LIKE ?
                OR b.borrower_id LIKE ?
                OR tl.tool_name LIKE ?
                OR t.barcode LIKE ?
                OR t.status LIKE ?
                OR a.first_name LIKE ?
                OR a.last_name LIKE ?
            )
        """
        wildcard = f"%{search}%"
        params.extend([wildcard, wildcard, wildcard, wildcard, wildcard, wildcard, wildcard])

    if status:
        query += " AND t.status = ?"
        params.append(status)

    if borrower:
        query += " AND b.borrower_id LIKE ?"
        params.append(f"%{borrower}%")

    if tool:
        query += " AND tl.tool_name LIKE ?"
        params.append(f"%{tool}%")

    if date_from:
        query += " AND DATE(t.borrow_date) >= DATE(?)"
        params.append(date_from)

    if date_to:
        query += " AND DATE(t.borrow_date) <= DATE(?)"
        params.append(date_to)

    query += " ORDER BY t.id DESC"

    rows = db.execute(query, params).fetchall()

    return render_template(
        "transactions.html",
        transactions=rows,
        search=search,
        selected_status=status,
        borrower=borrower,
        tool=tool,
        date_from=date_from,
        date_to=date_to,
    )


@app.route("/reports")
@login_required
def reports():
    db = get_db()

    most_borrowed_tools = db.execute(
        """
        SELECT tl.tool_name, tl.tool_code, tl.barcode, COUNT(*) AS borrow_count
        FROM transactions t
        JOIN tools tl ON tl.id = t.tool_id
        GROUP BY t.tool_id
        ORDER BY borrow_count DESC
        LIMIT 10
        """
    ).fetchall()

    currently_borrowed = db.execute(
        """
        SELECT t.id,
               b.borrower_name,
               b.borrower_id,
               tl.tool_name,
               tl.tool_code,
               t.barcode,
               t.borrow_date,
               t.expected_return_date,
               CASE
                   WHEN DATE(t.expected_return_date) < DATE('now') THEN 1
                   ELSE 0
               END AS is_overdue
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
        WHERE t.status = 'borrowed'
        ORDER BY t.borrow_date ASC
        """
    ).fetchall()

    borrow_summary = db.execute(
        """
        SELECT DATE(borrow_date) AS date, COUNT(*) AS count
        FROM transactions
        GROUP BY DATE(borrow_date)
        ORDER BY date ASC
        LIMIT 30
        """
    ).fetchall()

    return_summary = db.execute(
        """
        SELECT DATE(return_date) AS date, COUNT(*) AS count
        FROM transactions
        WHERE return_date IS NOT NULL
        GROUP BY DATE(return_date)
        ORDER BY date ASC
        LIMIT 30
        """
    ).fetchall()

    return render_template(
        "reports.html",
        most_borrowed_tools=most_borrowed_tools,
        currently_borrowed=currently_borrowed,
        borrow_summary=rows_to_dicts(borrow_summary),
        return_summary=rows_to_dicts(return_summary),
    )


@app.route("/export/tools.csv")
@login_required
def export_tools_csv():
    db = get_db()
    tools = db.execute(
        """
        SELECT tool_name, tool_code, category, description, quantity,
               available_quantity, barcode, barcode_image, status, date_added
        FROM tools
        ORDER BY id DESC
        """
    ).fetchall()

    view_mode = request.args.get("view", "csv").strip().lower()
    if view_mode == "table":
        headers = [
            "Tool Name",
            "Tool Code",
            "Category",
            "Description",
            "Quantity",
            "Available Quantity",
            "Barcode",
            "Barcode Image",
            "Status",
            "Date Added",
        ]
        table_rows = [
            [
                row["tool_name"],
                row["tool_code"],
                row["category"],
                row["description"],
                row["quantity"],
                row["available_quantity"],
                row["barcode"],
                row["barcode_image"],
                row["status"],
                row["date_added"],
            ]
            for row in tools
        ]
        return render_template(
            "export_table.html",
            title="Tools Export (Printable Table)",
            filename="tools_export.csv",
            headers=headers,
            rows=table_rows,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            csv_download_url=url_for("export_tools_csv"),
        )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Tool Name",
            "Tool Code",
            "Category",
            "Description",
            "Quantity",
            "Available Quantity",
            "Barcode",
            "Barcode Image",
            "Status",
            "Date Added",
        ]
    )

    for row in tools:
        writer.writerow(
            [
                row["tool_name"],
                row["tool_code"],
                row["category"],
                row["description"],
                row["quantity"],
                row["available_quantity"],
                row["barcode"],
                row["barcode_image"],
                row["status"],
                row["date_added"],
            ]
        )

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=tools_export.csv"},
    )


@app.route("/export/transactions.csv")
@login_required
def export_transactions_csv():
    db = get_db()
    rows = db.execute(
        """
        SELECT t.id,
               b.borrower_name,
               b.borrower_id,
               tl.tool_name,
               t.barcode,
               t.borrow_date,
               t.expected_return_date,
               t.return_date,
               t.status,
               TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
        LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        ORDER BY t.id DESC
        """
    ).fetchall()

    view_mode = request.args.get("view", "csv").strip().lower()
    if view_mode == "table":
        headers = [
            "Transaction ID",
            "Borrower Name",
            "Borrower ID",
            "Tool Name",
            "Barcode",
            "Borrow Date",
            "Expected Return Date",
            "Return Date",
            "Status",
            "Lent By",
        ]
        table_rows = [
            [
                row["id"],
                row["borrower_name"],
                row["borrower_id"],
                row["tool_name"],
                row["barcode"],
                row["borrow_date"],
                row["expected_return_date"],
                row["return_date"],
                row["status"],
                row["lent_by_admin_name"],
            ]
            for row in rows
        ]
        return render_template(
            "export_table.html",
            title="Transactions Export (Printable Table)",
            filename="transactions_export.csv",
            headers=headers,
            rows=table_rows,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            csv_download_url=url_for("export_transactions_csv"),
        )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Transaction ID",
            "Borrower Name",
            "Borrower ID",
            "Tool Name",
            "Barcode",
            "Borrow Date",
            "Expected Return Date",
            "Return Date",
            "Status",
            "Lent By",
        ]
    )

    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["borrower_name"],
                row["borrower_id"],
                row["tool_name"],
                row["barcode"],
                row["borrow_date"],
                row["expected_return_date"],
                row["return_date"],
                row["status"],
                row["lent_by_admin_name"],
            ]
        )

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions_export.csv"},
    )


@app.route("/api/tool/<barcode>")
@login_required
def api_tool_by_barcode(barcode):
    db = get_db()
    tool = db.execute(
        """
        SELECT id, tool_name, tool_code, category, quantity,
             available_quantity, barcode, barcode_image, tool_image, status
        FROM tools WHERE barcode = ?
        """,
        (barcode.strip(),),
    ).fetchone()

    if tool is None:
        return {"found": False}

    return {
        "found": True,
        "tool": {
            "id": tool["id"],
            "tool_name": tool["tool_name"],
            "tool_code": tool["tool_code"],
            "category": tool["category"],
            "quantity": tool["quantity"],
            "available_quantity": tool["available_quantity"],
            "barcode": tool["barcode"],
            "barcode_image": tool["barcode_image"],
            "tool_image": tool["tool_image"],
            "status": normalize_tool_status(tool),
        },
    }


@app.route("/api/borrowed/<barcode>")
@login_required
def api_borrowed_by_barcode(barcode):
    db = get_db()
    row = db.execute(
        """
        SELECT t.id,
               t.borrow_date,
               t.expected_return_date,
               t.status,
               b.borrower_name,
               b.borrower_id,
               b.course_department,
               b.contact_number,
               tl.tool_name,
               tl.tool_code,
               tl.category,
             t.barcode,
             TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS lent_by_admin_name
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
         LEFT JOIN admins a ON a.id = t.lent_by_admin_id
        WHERE t.barcode = ? AND t.status = 'borrowed'
        ORDER BY t.borrow_date ASC, t.id ASC
        LIMIT 1
        """,
        (barcode.strip(),),
    ).fetchone()

    if row is None:
        return {"found": False}

    is_overdue = False
    expected_date = parse_date_input(row["expected_return_date"])
    if expected_date and date.today() > expected_date:
        is_overdue = True

    return {
        "found": True,
        "transaction": {
            "id": row["id"],
            "borrow_date": row["borrow_date"],
            "expected_return_date": row["expected_return_date"],
            "status": row["status"],
            "is_overdue": is_overdue,
            "borrower_name": row["borrower_name"],
            "borrower_id": row["borrower_id"],
            "course_department": row["course_department"],
            "contact_number": row["contact_number"],
            "tool_name": row["tool_name"],
            "tool_code": row["tool_code"],
            "category": row["category"],
            "barcode": row["barcode"],
            "lent_by_admin_name": row["lent_by_admin_name"],
        },
    }


@app.template_filter("status_label")
def status_label(status_value):
    status_map = {
        "borrowed": "Borrowed",
        "returned": "Returned",
        "returned_overdue": "Returned (Overdue)",
    }
    return status_map.get(status_value, str(status_value).title())


@app.template_filter("status_badge")
def status_badge(status_value):
    if status_value == "borrowed":
        return "bg-amber-100 text-amber-800"
    if status_value == "returned_overdue":
        return "bg-red-100 text-red-800"
    if status_value == "returned":
        return "bg-emerald-100 text-emerald-800"
    return "bg-slate-100 text-slate-800"


if __name__ == "__main__":
    app.run(
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "1") == "1",
    )
