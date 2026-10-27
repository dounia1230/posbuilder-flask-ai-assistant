"""Accès PostgreSQL/SQLite et migration non destructive de l'historique."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from flask import current_app, g
from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    create_engine, event, select,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool


def utc_now():
    return datetime.now(timezone.utc).isoformat()


metadata = MetaData()
conversations = Table(
    "conversations", metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("specialty", Text, nullable=False),
    Column("created_at", Text, nullable=False, default=utc_now),
    Column("updated_at", Text, nullable=False, default=utc_now),
)
messages = Table(
    "messages", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conversation_id", Text, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", Text, nullable=False, default=utc_now),
    CheckConstraint("role IN ('user', 'assistant')", name="message_role"),
)
Index("messages_conversation_id", messages.c.conversation_id, messages.c.id)
documents = Table(
    "documents", metadata,
    Column("id", Text, primary_key=True),
    Column("message_id", Integer, ForeignKey("messages.id", ondelete="CASCADE"), unique=True, nullable=False),
    Column("filename", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", Text, nullable=False, default=utc_now),
)


def database_url():
    configured = current_app.config.get("DATABASE_URL")
    if configured:
        url = make_url(configured)
        if url.drivername in ("postgres", "postgresql"):
            url = url.set(drivername="postgresql+psycopg")
        if url.get_backend_name() not in ("sqlite", "postgresql"):
            raise ValueError("DATABASE_URL doit utiliser PostgreSQL ou SQLite.")
        return url
    path = Path(current_app.config["DATABASE"]).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return URL.create("sqlite", database=str(path))


def get_engine():
    url = database_url()
    engines = current_app.extensions.setdefault("database_engines", {})
    if url not in engines:
        options = {"pool_pre_ping": True}
        if url.get_backend_name() == "sqlite":
            options["poolclass"] = NullPool
        else:
            options["connect_args"] = {"connect_timeout": 5}
        engine = create_engine(url, **options)
        if engine.dialect.name == "sqlite":
            @event.listens_for(engine, "connect")
            def enable_foreign_keys(connection, record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()
        engines[url] = engine
    return engines[url]


def get_db():
    if "db" not in g:
        g.db = get_engine().connect()
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    metadata.create_all(get_engine())


def migrate_sqlite(source, target_engine):
    """Copie les discussions absentes sans modifier ni supprimer la base source."""
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("La base SQLite source est introuvable.")
    counts = {"conversations": 0, "messages": 0, "documents": 0}
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as legacy:
        legacy.row_factory = sqlite3.Row
        has_documents = legacy.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
        with target_engine.begin() as target:
            for row in legacy.execute("SELECT * FROM conversations ORDER BY rowid"):
                conversation = dict(row)
                exists = target.execute(select(conversations.c.id).where(
                    conversations.c.id == conversation["id"]
                )).first()
                if exists:
                    continue
                target.execute(conversations.insert().values(**conversation))
                counts["conversations"] += 1
                for item in legacy.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation["id"],)
                ):
                    message = dict(item)
                    old_id = message.pop("id")
                    new_id = target.execute(messages.insert().values(**message)).inserted_primary_key[0]
                    counts["messages"] += 1
                    if has_documents:
                        for old_document in legacy.execute("SELECT * FROM documents WHERE message_id = ?", (old_id,)):
                            document = dict(old_document)
                            document["message_id"] = new_id
                            target.execute(documents.insert().values(**document))
                            counts["documents"] += 1
    return counts
