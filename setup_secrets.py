"""
Databricks Secret Scope Setup Script:
Creates the workspace secret scope and registers the Lakebase connection URL.

Usage:
    python setup_secrets.py
"""
import getpass
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace

w = WorkspaceClient()

try:
    w.secrets.create_scope(scope="database")
except Exception:
    pass

w.secrets.put_secret(
    scope="database",
    key="lakebase-url",
    string_value=getpass.getpass("Paste your Lakebase URL: ")
)

try:
    w.secrets.put_acl(
        scope="database",
        principal="users",
        permission=workspace.AclPermission.READ,
    )
except Exception:
    pass
