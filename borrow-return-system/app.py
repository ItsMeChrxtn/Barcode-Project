import csv
import os
import random
import sqlite3
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
    session,
    url_for,
)
import barcode
from barcode.writer import ImageWriter
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database.db")
BARCODE_DIR = os.path.join(BASE_DIR, "static", "barcodes")
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
        "SELECT id, username FROM admins ORDER BY username ASC"
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
               available_quantity, barcode, barcode_image, status
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
               t.barcode
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
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
    }


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


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

    cursor = db.execute(
        """
        INSERT INTO transactions
        (borrower_id, tool_id, barcode, borrow_date, expected_return_date, return_date, status)
        VALUES (?, ?, ?, ?, ?, NULL, 'borrowed')
        """,
        (borrower_id, tool["id"], barcode_value, borrow_timestamp, ""),
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
               t.barcode
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
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
               t.barcode
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
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
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        form_data = {"username": username}

        if not username or not password or not confirm_password:
            flash("Username, password, and confirmation are required.", "danger")
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
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        db.commit()
        flash("New admin account created successfully.", "success")
        return redirect(url_for("admins"))

    return render_admins_page(db)


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
               available_quantity, barcode, barcode_image, status, date_added
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
    selected_ids = request.form.getlist("tool_ids")
    valid_ids = []
    for raw_id in selected_ids:
        try:
            valid_ids.append(int(raw_id))
        except ValueError:
            continue

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
        form_data = {
            "tool_name": tool_name,
            "category": category,
            "description": description,
            "quantity": quantity_text,
        }

        tool_code = generate_next_tool_code(db)

        if not all([tool_name, category]):
            flash("Tool name and category are required.", "danger")
            return redirect(url_for("tools"))

        if category not in CATEGORY_OPTIONS:
            flash("Please select a valid category.", "danger")
            return redirect(url_for("tools"))

        try:
            quantity = int(quantity_text)
            if quantity < 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a non-negative number.", "danger")
            return redirect(url_for("tools"))

        barcode = generate_unique_barcode(db)

        duplicate_code = db.execute(
            "SELECT id FROM tools WHERE tool_code = ?", (tool_code,)
        ).fetchone()
        if duplicate_code:
            flash("Could not generate a unique tool code. Please try again.", "danger")
            return redirect(url_for("tools"))

        barcode_image = create_barcode_image(barcode)
        status = "Available" if quantity > 0 else "Unavailable"
        cursor = db.execute(
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
                quantity,
                barcode,
                barcode_image,
                status,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        db.commit()

        flash(f"Tool added successfully. Barcode generated: {barcode}", "success")
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
    has_active_borrow = db.execute(
        "SELECT id FROM transactions WHERE tool_id = ? AND status = 'borrowed' LIMIT 1",
        (tool_id,),
    ).fetchone()
    if has_active_borrow:
        flash("Cannot delete tool while it is currently borrowed.", "danger")
        return redirect(url_for("tools"))

    db.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    db.commit()

    flash("Tool deleted successfully.", "info")
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
               t.status
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
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
            )
        """
        wildcard = f"%{search}%"
        params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

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
               available_quantity, barcode, status, date_added
        FROM tools
        ORDER BY id DESC
        """
    ).fetchall()

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
               t.status
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
        ORDER BY t.id DESC
        """
    ).fetchall()

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
             available_quantity, barcode, barcode_image, status
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
               t.barcode
        FROM transactions t
        JOIN borrowers b ON b.id = t.borrower_id
        JOIN tools tl ON tl.id = t.tool_id
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
