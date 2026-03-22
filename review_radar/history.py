"""分析历史存储 — SQLite"""

import json
import sqlite3
import time
from pathlib import Path

_DEFAULT_DB = Path.home() / ".review_radar" / "history.db"


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """获取数据库连接，自动建表"""
    path = db_path or _DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT NOT NULL,
            timestamp REAL NOT NULL,
            countries TEXT NOT NULL,
            platforms TEXT NOT NULL,
            review_count INTEGER NOT NULL DEFAULT 0,
            aggregated_json TEXT,
            report_text TEXT
        )
    """)
    conn.commit()
    return conn


def save_analysis(
    app_name: str,
    countries: list[str],
    platforms: list[str],
    review_count: int,
    aggregated: dict | None = None,
    report: str = "",
    db_path: Path | None = None,
) -> int:
    """保存一次分析记录，返回记录 ID"""
    conn = _get_db(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO analyses (app_name, timestamp, countries, platforms, review_count, aggregated_json, report_text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                app_name,
                time.time(),
                json.dumps(countries, ensure_ascii=False),
                json.dumps(platforms, ensure_ascii=False),
                review_count,
                json.dumps(aggregated, ensure_ascii=False) if aggregated else None,
                report,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_analyses(app_name: str | None = None, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """列出分析历史"""
    conn = _get_db(db_path)
    try:
        if app_name:
            rows = conn.execute(
                "SELECT id, app_name, timestamp, countries, platforms, review_count FROM analyses WHERE app_name = ? ORDER BY timestamp DESC LIMIT ?",
                (app_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, app_name, timestamp, countries, platforms, review_count FROM analyses ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_analysis(analysis_id: int, db_path: Path | None = None) -> dict | None:
    """获取单条分析记录（含完整数据）"""
    conn = _get_db(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("aggregated_json"):
            result["aggregated"] = json.loads(result["aggregated_json"])
        if result.get("countries"):
            result["countries"] = json.loads(result["countries"])
        if result.get("platforms"):
            result["platforms"] = json.loads(result["platforms"])
        return result
    finally:
        conn.close()


def delete_analysis(analysis_id: int, db_path: Path | None = None) -> bool:
    """删除一条分析记录"""
    conn = _get_db(db_path)
    try:
        cur = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
