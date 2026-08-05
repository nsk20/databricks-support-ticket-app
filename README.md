# Databricks Internal Support Ticket Application

An enterprise-grade support ticket management platform built with **Flask** and **Databricks Lakebase** (managed PostgreSQL). Designed for high-throughput operational tracking, ticket lifecycle management, and real-time interaction history.

---

## Architecture & Database Schema

### Relational Schema (Databricks Lakebase / PostgreSQL)

- **`tickets`**:
  - `ticket_id`: `SERIAL PRIMARY KEY`
  - `title`: `TEXT NOT NULL`
  - `status`: `TEXT NOT NULL DEFAULT 'open'` (`'open'`, `'in_progress'`, `'resolved'`)
  - `priority`: `TEXT NOT NULL DEFAULT 'medium'` (`'low'`, `'medium'`, `'high'`, `'urgent'`)
  - `category`: `TEXT NOT NULL DEFAULT 'general'` (`'general'`, `'billing'`, `'technical'`, `'bug'`)
  - `created_by`: `TEXT NOT NULL`
  - `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT now()`

- **`ticket_messages`**:
  - `message_id`: `SERIAL PRIMARY KEY`
  - `ticket_id`: `INTEGER NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE`
  - `message_text`: `TEXT NOT NULL`
  - `author`: `TEXT NOT NULL`
  - `created_at`: `TIMESTAMPTZ NOT NULL DEFAULT now()`

---

## Core Capabilities

- **Automatic Schema Migration & Initial Seeding:** Auto-provisions required tables on application startup and seeds default workspace tickets if empty.
- **RESTful API Backend:**
  - `GET /api/me`: Resolves current authenticated user identity from workspace headers.
  - `GET /api/tickets`: Retrieves operational tickets with status filtering (`?status=open|in_progress|resolved`).
  - `GET /api/tickets/<id>`: Fetches ticket metadata along with complete message history ordered chronologically.
  - `POST /api/tickets`: Creates a new ticket.
  - `POST /api/tickets/<id>/messages`: Appends a reply or status comment to an existing ticket thread.
  - `PATCH /api/tickets/<id>/status`: Updates ticket lifecycle state.
  - `DELETE /api/tickets/<id>`: Permanently removes a ticket and cascades message deletion.
  - `GET /api/stats`: Calculates real-time system metrics (total volume, status distribution, priority distribution).
- **Interactive UI Dashboard:** Responsive single-page interface featuring metric counters, queue filters, two-column detail views, confirmation modals, and real-time status controls.

---

## Deployment & Setup

### Local Setup

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment:**
   ```bash
   export LAKEBASE_URL="postgresql://<role>:<password>@<host>:5432/databricks_postgres?sslmode=require"
   python app.py
   ```

### Databricks App Deployment
Configured for native deployment on Databricks Apps using `app.yaml`:

```yaml
command:
  - "python"
  - "app.py"

env:
  - name: LAKEBASE_SECRET_SCOPE
    value: "database"
  - name: LAKEBASE_SECRET_KEY
    value: "lakebase-url"
```
