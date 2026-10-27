"""Tests d'intégration SQLite, sans appel à l'API du modèle."""

import importlib
from contextlib import closing
import csv
from io import BytesIO, StringIO
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        bootstrap = str(Path(cls.directory.name) / "bootstrap.sqlite3")
        with patch.dict(os.environ, {"DATABASE_PATH": bootstrap, "DATABASE_URL": ""}), \
                patch("dotenv.load_dotenv"), patch("openai.OpenAI"):
            cls.module = importlib.import_module("app")
        cls.app = cls.module.app
        cls.app.config["TESTING"] = True
        cls.addClassCleanup(lambda: [engine.dispose() for engine in cls.app.extensions.get("database_engines", {}).values()])

    def setUp(self):
        self.path = str(Path(self.directory.name) / f"{uuid4().hex}.sqlite3")
        self.app.config["DATABASE"] = self.path
        self.app.config["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "")
        if self.app.config["DATABASE_URL"]:
            if not (make_url(self.app.config["DATABASE_URL"]).database or "").endswith("_test"):
                raise RuntimeError("TEST_DATABASE_URL doit désigner une base dédiée dont le nom se termine par _test.")
        with self.app.app_context():
            if self.app.config["DATABASE_URL"]:
                from database import metadata
                metadata.drop_all(self.module.get_engine())
            self.module.init_db()
        self.client = self.app.test_client()

    def send(self, message="Bonjour", specialty="general", conversation_id=None, answer="Bonjour !"):
        with patch.object(self.module, "event_stream", return_value=iter([answer])) as stream:
            response = self.client.post("/prompt", json={
                "messages": [message],
                "specialty": specialty,
                "conversation_id": conversation_id,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), answer)
            sent_messages = stream.call_args.args[0]
            saved_id = response.headers["X-Conversation-ID"]
            response.close()
        return saved_id, sent_messages

    def test_initialization_is_repeatable_and_enforces_foreign_keys(self):
        self.send()
        with self.app.app_context():
            self.module.init_db()
            connection = self.module.get_db()
            self.assertEqual(connection.execute(select(func.count()).select_from(self.module.conversation_table)).scalar_one(), 1)
            with self.assertRaises(IntegrityError):
                connection.execute(self.module.message_table.insert().values(
                    conversation_id="missing", role="user", content="Bonjour",
                ))
            connection.rollback()

    def test_home_and_empty_conversation_list(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="saved-conversations"', page.get_data(as_text=True))
        self.assertEqual(self.client.get("/conversations").get_json(), {"conversations": []})

    def test_save_reload_and_reopen_database(self):
        message = "Explique l'équation x² = 4"
        answer = "**Solutions** : x = −2 ou x = 2."
        saved_id, _ = self.send(message, "math", answer=answer)
        # Un autre client et une autre connexion relisent les données sur disque.
        data = self.app.test_client().get(f"/conversations/{saved_id}").get_json()
        self.assertEqual(data["specialty"], "math")
        self.assertEqual(data["title"], message)
        self.assertEqual(data["messages"], [
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])
        with self.app.app_context(), self.module.get_engine().connect() as connection:
            self.assertEqual(connection.execute(select(func.count()).select_from(self.module.message_table)).scalar_one(), 2)
        listing = self.client.get("/conversations").get_json()["conversations"]
        self.assertEqual(listing[0]["id"], saved_id)

    def test_continue_uses_saved_history_and_preserves_markdown(self):
        saved_id, _ = self.send("Montre un exemple", "programming", answer="```python\nprint('salut')\n```")
        same_id, sent = self.send("Explique ce code", "programming", saved_id, "Il affiche un message.")
        self.assertEqual(same_id, saved_id)
        self.assertEqual([message["role"] for message in sent], ["system", "user", "assistant", "user"])
        self.assertEqual(sent[2]["content"], "```python\nprint('salut')\n```")
        self.assertEqual(sent[-1]["content"], "Explique ce code")
        self.assertEqual(len(self.client.get(f"/conversations/{saved_id}").get_json()["messages"]), 4)

    def test_new_conversations_remain_separate_and_use_their_specialty(self):
        first, _ = self.send("Question de maths", "math")
        second, sent = self.send("Aide en anglais", "languages")
        self.assertNotEqual(first, second)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["content"], self.module.SPECIALTIES["languages"]["instruction"])
        self.assertEqual(len(self.client.get("/conversations").get_json()["conversations"]), 2)

    def test_invalid_requests_do_not_write_data(self):
        cases = [
            ({"messages": []}, 400),
            ({"messages": [" "]}, 400),
            ({"messages": ["Salut"], "specialty": "unknown"}, 400),
            ({"messages": ["Salut"], "conversation_id": []}, 400),
            ({"messages": ["Salut"], "conversation_id": "missing"}, 404),
            ({"messages": ["Salut"], "conversation_id": "' OR 1=1 --"}, 404),
        ]
        with patch.object(self.module, "event_stream") as stream:
            for payload, status in cases:
                with self.subTest(payload=payload):
                    self.assertEqual(self.client.post("/prompt", json=payload).status_code, status)
            self.assertEqual(self.client.post("/prompt", data="text").status_code, 415)
            stream.assert_not_called()
        self.assertEqual(self.client.get("/conversations").get_json()["conversations"], [])

    def test_changing_specialty_requires_a_new_conversation(self):
        saved_id, _ = self.send(specialty="math")
        response = self.client.post("/prompt", json={
            "messages": ["Bonjour"], "specialty": "writing", "conversation_id": saved_id,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.client.get(f"/conversations/{saved_id}").get_json()["messages"]), 2)

    def test_failed_stream_keeps_user_message_without_saving_partial_answer(self):
        def broken_stream(conversation):
            yield "Début incomplet"
            raise RuntimeError("API indisponible")

        with patch.object(self.module, "event_stream", side_effect=broken_stream):
            response = self.client.post("/prompt", json={"messages": ["Question"]})
            saved_id = response.headers["X-Conversation-ID"]
            with self.assertRaises(RuntimeError):
                response.get_data()
            response.close()
        messages = self.client.get(f"/conversations/{saved_id}").get_json()["messages"]
        self.assertEqual(messages, [{"role": "user", "content": "Question"}])
        # La discussion peut être reprise après l'échec.
        _, sent = self.send("Nouvelle question", conversation_id=saved_id)
        self.assertEqual([message["role"] for message in sent], ["system", "user", "user"])

    def test_disconnected_client_does_not_save_partial_answer(self):
        with patch.object(self.module, "event_stream", return_value=iter(["Début", "Suite"])):
            response = self.client.post("/prompt", json={"messages": ["Question"]})
            saved_id = response.headers["X-Conversation-ID"]
            response.close()
        messages = self.client.get(f"/conversations/{saved_id}").get_json()["messages"]
        self.assertEqual(messages, [{"role": "user", "content": "Question"}])

    def test_missing_conversation_returns_404(self):
        self.assertEqual(self.client.get("/conversations/missing").status_code, 404)


















    def test_sqlite_migration_preserves_source_and_is_repeatable(self):
        source = Path(self.directory.name) / f"legacy-{uuid4().hex}.sqlite3"
        with closing(sqlite3.connect(source)) as legacy:
            legacy.executescript("""
                CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, specialty TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id TEXT, role TEXT, content TEXT, created_at TEXT);
            """)
            legacy.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?)", ("legacy", "Ancienne discussion", "math", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
            legacy.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", [
                (100, "legacy", "user", "Résous x = 2", "2026-01-01T00:00:00Z"),
                (101, "legacy", "assistant", "La réponse est 2.", "2026-01-01T00:00:01Z"),
            ])
            legacy.commit()
        with self.app.app_context():
            engine = self.module.get_engine()
            self.assertEqual(self.module.migrate_sqlite(source, engine), {"conversations": 1, "messages": 2, "documents": 0})
            self.assertEqual(self.module.migrate_sqlite(source, engine), {"conversations": 0, "messages": 0, "documents": 0})
        imported = self.client.get("/conversations/legacy").get_json()
        self.assertEqual([message["role"] for message in imported["messages"]], ["user", "assistant"])
        _, sent = self.send("Encore une question", "math", "legacy")
        self.assertEqual(sent[2]["content"], "La réponse est 2.")
        with closing(sqlite3.connect(source)) as legacy:
            self.assertEqual(legacy.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
