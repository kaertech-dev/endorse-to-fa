import bcrypt
from config import get_db_connection, get_connect_all
# ---------------------------------------------------------------------------
# Database configuration (matches your existing Python env-var pattern)
# ---------------------------------------------------------------------------

def check_badge(plain_badge: str, stored_hash: str) -> bool:
    """
    Verify a typed-in badge against the bcrypt hash stored in userv2.badge
    (as produced by migrate_passwords.py).
    """
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(plain_badge.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        # stored_hash isn't a valid bcrypt hash (e.g. still plaintext / not migrated yet)
        return False


def authenticate(employee_num: str, badge_raw: str):
    """
    Verify credentials against fa.userv2.
    employee_num = username, badge (bcrypt hash) = password.
    Returns the user row dict on success, or None on failure.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT employee_num, employee_name, badge
                FROM userv2
                WHERE employee_num = %s
                LIMIT 1
                """,
                (employee_num,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    if not check_badge(badge_raw, row["badge"]):
        return None
    return row


def selected_station(station: str) -> bool:
    """
    Check if the station exists in the main_copy table.
    Returns True if it exists, False otherwise.
    """
    conn = get_connect_all()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE station = %s
                LIMIT 1
                """,
                (station,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    return row is not None


def selected_tables(table: str) -> bool:
    """
    Check if the table exists in the main_copy table.
    Returns True if it exists, False otherwise.
    """
    conn = get_connect_all()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_name = %s
                LIMIT 1
                """,
                (table,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    return row is not None


def get_all_and_check_main(parse_all: str) -> list:
    """
    Split a string by commas and strip whitespace from each item.
    Returns a list of non-empty items.
    """
    return [item.strip() for item in parse_all.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Serial validation against a product/model's master registry table
#
#   <product_schema>.<model>_main
#   e.g. product="energous", model="esense" -> energous.esense_main
#
# `product` and `model` are values that originated from the UI dropdowns,
# so before we ever build a SQL identifier out of them we re-verify the
# exact schema/table pair against information_schema using a parameterized
# query. Only a pair that is confirmed to actually exist gets turned into
# a (backtick-quoted) identifier for the follow-up SELECT.
# ---------------------------------------------------------------------------
def _quote_ident(name: str) -> str:
    """Safely quote a MySQL identifier (schema or table name)."""
    return "`" + name.replace("`", "``") + "`"


def _table_exists(schema: str, table: str) -> bool:
    """Parameterized existence check for a specific schema.table pair."""
    conn = get_connect_all()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                LIMIT 1
                """,
                (schema, table),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def check_serial_in_main(product: str, model: str, serial_num: str) -> dict:
    """
    Check whether serial_num exists in <product>.<model>_main, and if so,
    pull its po_num so the PO field can be auto-filled instead of typed
    in by the user.

    Returns:
        {
            "table_checked": "energous.esense_main",
            "table_exists": True/False,   # does that _main table exist at all?
            "found": True/False,          # is serial_num a row in it?
            "po_num": "<value>" or None,  # only set when found is True
        }
    """
    result = {"table_checked": None, "table_exists": False, "found": False, "po_num": None}
    if not product or not model or not serial_num:
        return result

    table_name = f"{model}_main"
    result["table_checked"] = f"{product}.{table_name}"

    if not _table_exists(product, table_name):
        return result
    result["table_exists"] = True

    conn = get_connect_all()
    try:
        with conn.cursor() as cur:
            query = (
                f"SELECT po_num FROM {_quote_ident(product)}.{_quote_ident(table_name)} "
                "WHERE serial_num = %s LIMIT 1"
            )
            cur.execute(query, (serial_num,))
            row = cur.fetchone()
    finally:
        conn.close()

    result["found"] = row is not None
    if row is not None:
        result["po_num"] = row["po_num"]
    return result