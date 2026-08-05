"""
Databricks Internal Support Ticket Application Backend

REST API for support tickets, message threads, status transitions, and workspace identity

Operational data persistence backed by Databricks Lakebase (Managed PostgreSQL)

Run locally:
    python app.py
Deploy as a Databricks App using app.yaml.
"""

import logging
import os
from datetime import date, datetime
from flask import Flask, jsonify, render_template, request

try:
    from databricks.sdk import WorkspaceClient
    _w = WorkspaceClient()
except Exception:
    _w = None

import lakebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("support-ticket-app")

app = Flask(__name__)


def _format_datetime(val):
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _format_dict(row):
    if not row:
        return row
    return {k: _format_datetime(v) for k, v in row.items()}


def _current_user_email() -> str:
    """
    Resolve the current user's email identity.
    Databricks Apps inject X-Forwarded-Email header on every request.
    Falls back to Databricks SDK current user or a default workspace user for local dev.
    """
    header_email = request.headers.get("X-Forwarded-Email")
    if header_email:
        return header_email
    if _w is not None:
        try:
            me = _w.current_user.me()
            if me and me.user_name:
                return me.user_name
        except Exception as err:
            logger.debug(f"SDK me() call failed: {err}")
    return "workspace.user@databricks.com"


# Initialize database schema and seeds on module load
try:
    lakebase.init_db()
    logger.info("Lakebase database initialization completed successfully.")
except Exception as err:
    logger.error(f"Database initialization failed on startup: {err}")


@app.errorhandler(Exception)
def handle_exception(err):
    """Ensure unhandled errors return structured JSON."""
    logger.exception("Unhandled exception while processing request")
    status_code = getattr(err, "code", 500)
    if not isinstance(status_code, int):
        status_code = 500
    return jsonify({"error": str(err)}), status_code


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/me", methods=["GET"])
def get_current_user():
    return jsonify({"email": _current_user_email()})


@app.route("/api/tickets", methods=["GET"])
def get_tickets():
    """Retrieve all tickets with optional status filtering."""
    status_filter = request.args.get("status", "").strip().lower()
    
    if status_filter and status_filter != "all":
        sql = """
            SELECT ticket_id, title, status, priority, category, created_by, created_at
            FROM tickets
            WHERE status = %s
            ORDER BY created_at DESC
        """
        rows = lakebase.run_query(sql, (status_filter,))
    else:
        sql = """
            SELECT ticket_id, title, status, priority, category, created_by, created_at
            FROM tickets
            ORDER BY created_at DESC
        """
        rows = lakebase.run_query(sql)

    formatted_rows = [_format_dict(dict(r)) for r in rows]
    return jsonify(formatted_rows)


@app.route("/api/tickets/<int:ticket_id>", methods=["GET"])
def get_ticket_details(ticket_id: int):
    """Retrieve a specific ticket and all its ordered messages."""
    ticket_rows = lakebase.run_query(
        "SELECT ticket_id, title, status, priority, category, created_by, created_at FROM tickets WHERE ticket_id = %s",
        (ticket_id,),
    )
    if not ticket_rows:
        return jsonify({"error": f"Ticket #{ticket_id} not found"}), 404

    ticket = _format_dict(dict(ticket_rows[0]))

    message_rows = lakebase.run_query(
        """
        SELECT message_id, ticket_id, message_text, author, created_at
        FROM ticket_messages
        WHERE ticket_id = %s
        ORDER BY created_at ASC
        """,
        (ticket_id,),
    )
    ticket["messages"] = [_format_dict(dict(m)) for m in message_rows]
    return jsonify(ticket)


@app.route("/api/tickets", methods=["POST"])
def create_ticket():
    """Create a new support ticket."""
    data = request.get_json(silent=True) or request.form
    title = (data.get("title") or "").strip()
    priority = (data.get("priority") or "medium").strip().lower()
    category = (data.get("category") or "general").strip().lower()

    if not title:
        return jsonify({"error": "Title is required"}), 400

    valid_priorities = {"low", "medium", "high", "urgent"}
    if priority not in valid_priorities:
        priority = "medium"

    valid_categories = {"general", "billing", "technical", "bug"}
    if category not in valid_categories:
        category = "general"

    created_by = _current_user_email()

    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tickets (title, status, priority, category, created_by)
                VALUES (%s, 'open', %s, %s, %s)
                RETURNING ticket_id, title, status, priority, category, created_by, created_at;
                """,
                (title, priority, category, created_by),
            )
            row = cur.fetchone()
            conn.commit()

    return jsonify(_format_dict(dict(row))), 201


@app.route("/api/tickets/<int:ticket_id>/messages", methods=["POST"])
def add_ticket_message(ticket_id: int):
    """Add a message/reply to a ticket."""
    ticket_rows = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket_rows:
        return jsonify({"error": f"Ticket #{ticket_id} not found"}), 404

    data = request.get_json(silent=True) or request.form
    message_text = (data.get("message_text") or "").strip()

    if not message_text:
        return jsonify({"error": "Message text is required"}), 400

    author = _current_user_email()

    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ticket_messages (ticket_id, message_text, author)
                VALUES (%s, %s, %s)
                RETURNING message_id, ticket_id, message_text, author, created_at;
                """,
                (ticket_id, message_text, author),
            )
            row = cur.fetchone()
            conn.commit()

    return jsonify(_format_dict(dict(row))), 201


@app.route("/api/tickets/<int:ticket_id>/status", methods=["PATCH"])
def update_ticket_status(ticket_id: int):
    """Update a ticket's status ('open', 'in_progress', 'resolved')."""
    data = request.get_json(silent=True) or request.form
    new_status = (data.get("status") or "").strip().lower()

    valid_statuses = {"open", "in_progress", "resolved"}
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status: '{new_status}'. Must be one of {list(valid_statuses)}"}), 400

    ticket_rows = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket_rows:
        return jsonify({"error": f"Ticket #{ticket_id} not found"}), 404

    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE tickets
                SET status = %s
                WHERE ticket_id = %s
                RETURNING ticket_id, title, status, priority, category, created_by, created_at;
                """,
                (new_status, ticket_id),
            )
            row = cur.fetchone()
            conn.commit()

    return jsonify(_format_dict(dict(row)))


@app.route("/api/tickets/<int:ticket_id>", methods=["DELETE"])
def delete_ticket(ticket_id: int):
    """Delete a ticket and its associated messages."""
    ticket_rows = lakebase.run_query(
        "SELECT ticket_id FROM tickets WHERE ticket_id = %s", (ticket_id,)
    )
    if not ticket_rows:
        return jsonify({"error": f"Ticket #{ticket_id} not found"}), 404

    lakebase.run_write("DELETE FROM tickets WHERE ticket_id = %s", (ticket_id,))
    return jsonify({"message": "Ticket deleted successfully", "ticket_id": ticket_id})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Return ticket summary statistics."""
    total_res = lakebase.run_query("SELECT COUNT(*) AS count FROM tickets;")
    total_count = total_res[0]["count"] if total_res else 0

    status_res = lakebase.run_query(
        "SELECT status, COUNT(*) AS count FROM tickets GROUP BY status;"
    )
    status_counts = {"open": 0, "in_progress": 0, "resolved": 0}
    for row in status_res:
        st = row["status"]
        if st in status_counts:
            status_counts[st] = row["count"]

    priority_res = lakebase.run_query(
        "SELECT priority, COUNT(*) AS count FROM tickets GROUP BY priority;"
    )
    priority_counts = {"low": 0, "medium": 0, "high": 0, "urgent": 0}
    for row in priority_res:
        pr = row["priority"]
        if pr in priority_counts:
            priority_counts[pr] = row["count"]

    return jsonify({
        "total": total_count,
        "status": status_counts,
        "priority": priority_counts,
    })


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", 8000))
    app.run(debug=True, host=host, port=port)