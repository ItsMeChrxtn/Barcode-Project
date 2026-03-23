import random
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

import barcode
from barcode.writer import ImageWriter
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "monitoring.db"
BARCODE_DIR = BASE_DIR / "static" / "barcodes"


app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-with-a-random-secret-key"



def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()



def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            barcode TEXT UNIQUE NOT NULL,
            barcode_image TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS borrow_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            borrowed_at TEXT NOT NULL,
            returned_at TEXT,
            FOREIGN KEY (item_id) REFERENCES items(id),
            FOREIGN KEY (admin_id) REFERENCES admins(id)
        )
        """
    )
    db.commit()



def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view



def generate_unique_barcode(length=12):
    db = get_db()
    while True:
        barcode_number = "".join(str(random.randint(0, 9)) for _ in range(length))
        exists = db.execute(
            "SELECT id FROM items WHERE barcode = ?", (barcode_number,)
        ).fetchone()
        if not exists:
            return barcode_number



def create_barcode_image(barcode_number):
    BARCODE_DIR.mkdir(parents=True, exist_ok=True)
    file_stem = f"barcode_{barcode_number}"
    file_path_without_ext = BARCODE_DIR / file_stem

    code128 = barcode.get("code128", barcode_number, writer=ImageWriter())
    generated_path = code128.save(str(file_path_without_ext))

    # Store path relative to static for easier template rendering.
    return Path(generated_path).name


def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@app.before_request
def ensure_database():
    BARCODE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        admin = get_db().execute(
            "SELECT * FROM admins WHERE username = ?", (username,)
        ).fetchone()

        if admin and check_password_hash(admin["password"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    if "admin_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)

        try:
            db = get_db()
            db.execute(
                "INSERT INTO admins (username, password) VALUES (?, ?)",
                (username, password_hash),
            )
            db.commit()
            flash("Admin account created. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "error")

    return render_template("register.html")


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    items = db.execute("SELECT * FROM items ORDER BY id DESC").fetchall()
    active_borrows = db.execute(
        """
        SELECT
            bl.id,
            i.name AS item_name,
            i.type AS item_type,
            i.barcode,
            i.barcode_image,
            a.username AS admin_username,
            bl.borrowed_at
        FROM borrow_logs bl
        JOIN items i ON i.id = bl.item_id
        JOIN admins a ON a.id = bl.admin_id
        WHERE bl.returned_at IS NULL
        ORDER BY bl.borrowed_at DESC
        """
    ).fetchall()
    recent_transactions = db.execute(
        """
        SELECT
            bl.id,
            i.name AS item_name,
            i.type AS item_type,
            i.barcode,
            a.username AS admin_username,
            bl.borrowed_at,
            bl.returned_at
        FROM borrow_logs bl
        JOIN items i ON i.id = bl.item_id
        JOIN admins a ON a.id = bl.admin_id
        ORDER BY bl.id DESC
        LIMIT 20
        """
    ).fetchall()
    return render_template(
        "dashboard.html",
        items=items,
        active_borrows=active_borrows,
        recent_transactions=recent_transactions,
    )


@app.route("/add_item", methods=["GET"])
@login_required
def add_item():
    return render_template("add_item.html", generated_item=None)


@app.route("/generate_barcode", methods=["POST"])
@login_required
def generate_barcode():
    item_name = request.form.get("item_name", "").strip()
    item_type = request.form.get("item_type", "").strip()

    if not item_name or not item_type:
        flash("Item name and category are required.", "error")
        return redirect(url_for("add_item"))

    db = get_db()
    barcode_number = generate_unique_barcode()
    barcode_filename = create_barcode_image(barcode_number)

    db.execute(
        """
        INSERT INTO items (name, type, barcode, barcode_image)
        VALUES (?, ?, ?, ?)
        """,
        (item_name, item_type, barcode_number, barcode_filename),
    )
    db.commit()

    generated_item = db.execute(
        "SELECT * FROM items WHERE barcode = ?", (barcode_number,)
    ).fetchone()

    flash("Item and barcode created successfully.", "success")
    return render_template("add_item.html", generated_item=generated_item)


@app.route("/scan", methods=["GET", "POST"])
@login_required
def scan_barcode():
    db = get_db()
    scanned_item = None
    scan_result = None

    if request.method == "POST":
        barcode_number = request.form.get("barcode", "").strip()

        if not barcode_number:
            flash("Please scan or enter a barcode number.", "error")
            return redirect(url_for("scan_barcode"))

        item = db.execute(
            "SELECT * FROM items WHERE barcode = ?", (barcode_number,)
        ).fetchone()

        if not item:
            flash("Barcode not found in registered items.", "error")
            return redirect(url_for("scan_barcode"))

        scanned_item = item
        active_log = db.execute(
            """
            SELECT * FROM borrow_logs
            WHERE item_id = ? AND returned_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (item["id"],),
        ).fetchone()

        if active_log:
            db.execute(
                """
                UPDATE borrow_logs
                SET returned_at = ?
                WHERE id = ?
                """,
                (get_current_timestamp(), active_log["id"]),
            )
            db.commit()
            scan_result = "return"
            flash("Item returned successfully.", "success")
        else:
            db.execute(
                """
                INSERT INTO borrow_logs (item_id, admin_id, borrowed_at)
                VALUES (?, ?, ?)
                """,
                (item["id"], session["admin_id"], get_current_timestamp()),
            )
            db.commit()
            scan_result = "borrow"
            flash("Item borrowed successfully.", "success")

    active_borrows = db.execute(
        """
        SELECT
            bl.id,
            i.name AS item_name,
            i.type AS item_type,
            i.barcode,
            bl.borrowed_at,
            a.username AS admin_username
        FROM borrow_logs bl
        JOIN items i ON i.id = bl.item_id
        JOIN admins a ON a.id = bl.admin_id
        WHERE bl.returned_at IS NULL
        ORDER BY bl.borrowed_at DESC
        """
    ).fetchall()

    recent_transactions = db.execute(
        """
        SELECT
            bl.id,
            i.name AS item_name,
            i.type AS item_type,
            i.barcode,
            bl.borrowed_at,
            bl.returned_at,
            a.username AS admin_username
        FROM borrow_logs bl
        JOIN items i ON i.id = bl.item_id
        JOIN admins a ON a.id = bl.admin_id
        ORDER BY bl.id DESC
        LIMIT 30
        """
    ).fetchall()

    return render_template(
        "scan.html",
        scanned_item=scanned_item,
        scan_result=scan_result,
        active_borrows=active_borrows,
        recent_transactions=recent_transactions,
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    BARCODE_DIR.mkdir(parents=True, exist_ok=True)
    app.run(debug=True)
