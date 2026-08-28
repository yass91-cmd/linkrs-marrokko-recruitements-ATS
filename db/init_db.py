from pathlib import Path
from db.database import get_connection

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def init_db():
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print("Database schema initialized.")


if __name__ == "__main__":
    init_db()