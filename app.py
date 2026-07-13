# app.py
import os
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash
)
from config import get_db_connection
from functions import authenticate, check_serial_in_main
import pymysql
import pymysql.cursors
import bcrypt

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key-in-production")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "employee_num" not in session:
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Routes: auth
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        employee_num = request.form.get("employee_num", "").strip()
        badge = request.form.get("badge", "").strip()

        if not employee_num or not badge:
            flash("Enter both employee number and badge.", "error")
            return render_template("login.html")

        try:
            user = authenticate(employee_num, badge)
        except pymysql.MySQLError as e:
            flash(f"Database connection error: {e}", "error")
            return render_template("login.html")

        if user is None:
            flash("Employee number or badge is incorrect.", "error")
            return render_template("login.html")

        session["employee_num"] = user["employee_num"]
        session["employee_name"] = user["employee_name"]
        next_url = request.args.get("next") or url_for("endorse")
        return redirect(next_url)

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes: main endorsement page
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def endorse():
    return render_template(
        "endorse.html",
        employee_num=session["employee_num"],
        employee_name=session["employee_name"],
    )


# ---------------------------------------------------------------------------
# API: dropdown data
#
# Product  -> active schemas from projectsdb.projects
# Model    -> the part of each table name in that schema BEFORE the first "_"
# Station  -> the part of each table name AFTER the first "_"
#   e.g. table "faceware_packaging" => model "faceware", station "packaging"
# ---------------------------------------------------------------------------
def split_model_station(table_name: str):
    """Split a schema table name into (model, station) at the first underscore."""
    if "_" in table_name:
        model, _, station = table_name.partition("_")
    else:
        model, station = table_name, ""
    return model, station


def get_tables_for_schema(schemadb: str):
    """List all table names that live inside the given schema/database."""
    if not schemadb:
        return []
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TABLE_NAME
                FROM information_schema.tables
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
                """,
                (schemadb,),
            )
            return [r["TABLE_NAME"] for r in cur.fetchall()]
    except pymysql.MySQLError:
        return []
    finally:
        conn.close()


@app.route("/api/products")
@login_required
def api_products():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schemadb
                FROM projectsdb.projects
                WHERE status = 'active'
                ORDER BY schemadb
                """
            )
            rows = [r["schemadb"] for r in cur.fetchall() if r["schemadb"]]
    except pymysql.MySQLError:
        rows = []
    finally:
        conn.close()
    return jsonify(rows)


@app.route("/api/models")
@login_required
def api_models():
    # Here "product" is really the schemadb name selected from /api/products
    product = request.args.get("product", "").strip()
    tables = get_tables_for_schema(product)
    models = sorted({split_model_station(t)[0] for t in tables if t})
    return jsonify(models)


@app.route("/api/stations")
@login_required
def api_stations():
    product = request.args.get("product", "").strip()
    model = request.args.get("model", "").strip()
    tables = get_tables_for_schema(product)
    stations = sorted({
        split_model_station(t)[1]
        for t in tables
        if t and split_model_station(t)[0] == model and split_model_station(t)[1]
    })
    return jsonify(stations)


@app.route("/api/lookup_serial")
@login_required
def api_lookup_serial():
    """
    If this serial number already has an FA case in fa.main, return its
    current details so the form can be reviewed/edited rather than
    accidentally duplicated. If it's a brand-new serial, found=False and
    the user fills the form in from scratch.
    """
    serial = request.args.get("serial", "").strip()
    if not serial:
        return jsonify({"found": False})

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT product, model, station, test_failure, po_num
                FROM main_copy
                WHERE serial_num = %s
                LIMIT 1
                """,
                (serial,),
            )
            row = cur.fetchone()
    except pymysql.MySQLError:
        row = None
    finally:
        conn.close()

    if row is None:
        return jsonify({"found": False})
    return jsonify({
        "found": True,
        "product": row["product"],
        "model": row["model"],
        "station": row["station"],
        "failure_mode": row["test_failure"],
        "po": row["po_num"],
    })


@app.route("/api/check_serial_main")
@login_required
def api_check_serial_main():
    """
    Validate a serial number against the model's master registry table:
        <product>.<model>_main
    e.g. product="energous", model="esense" -> energous.esense_main

    This is the "is this a real, known unit" check, independent of whether
    it already has an FA case in main_copy.
    """
    product = request.args.get("product", "").strip()
    model = request.args.get("model", "").strip()
    serial = request.args.get("serial", "").strip()

    if not product or not model or not serial:
        return jsonify({"table_checked": None, "table_exists": False, "found": False})

    try:
        result = check_serial_in_main(product, model, serial)
    except pymysql.MySQLError as e:
        return jsonify({
            "table_checked": f"{product}.{model}_main",
            "table_exists": False,
            "found": False,
            "error": f"Database error: {e}",
        })

    return jsonify(result)


# ---------------------------------------------------------------------------
# API: submit endorsement
# ---------------------------------------------------------------------------
@app.route("/api/endorse", methods=["POST"])
@login_required
def api_endorse():
    data = request.get_json(force=True)

    serial_num = (data.get("serial_number") or "").strip()
    product = (data.get("product") or "").strip() or None
    model = (data.get("model") or "").strip() or None
    station = (data.get("station") or "").strip() or None
    test_failure = (data.get("failure_mode") or "").strip() or None

    if not serial_num:
        return jsonify({"success": False, "message": "Serial number is required."}), 400

    if not product or not model:
        return jsonify({"success": False, "message": "Product and model are required."}), 400

    # Server-side re-check (mirrors the client-side check) so the gate
    # can't be bypassed by calling this endpoint directly.
    try:
        check = check_serial_in_main(product, model, serial_num)
    except pymysql.MySQLError as e:
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500

    if not check["found"]:
        if not check["table_exists"]:
            message = f"Master table {check['table_checked']} does not exist."
        else:
            message = f"No record found for serial {serial_num} in {check['table_checked']}."
        return jsonify({"success": False, "message": message}), 400

    # PO is auto-filled from <product>.<model>_main, never typed in by the user.
    po_num = check["po_num"]

    # Endorser stored as employee_num only, per your latest version.
    endorser_label = f"{session['employee_num']}"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO main_copy
                    (serial_num, product, model, po_num, station,
                     test_failure, prod_endorser, faendorse_datetime, proposed_action, fa_class)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    product = VALUES(product),
                    model = VALUES(model),
                    po_num = VALUES(po_num),
                    station = VALUES(station),
                    test_failure = VALUES(test_failure),
                    prod_endorser = VALUES(prod_endorser),
                    faendorse_datetime = VALUES(faendorse_datetime)
                """,
                (
                    serial_num, product, model, po_num, station,
                    test_failure, endorser_label, datetime.now(), "open",
                ),
            )
    except pymysql.MySQLError as e:
        conn.close()
        return jsonify({"success": False, "message": f"Database error: {e}"}), 500
    conn.close()

    return jsonify({
        "success": True,
        "message": f"Serial {serial_num} endorsed to FA by {session['employee_name']}."
    })


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5005, debug=debug_mode, use_reloader=debug_mode)