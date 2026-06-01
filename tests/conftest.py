import os
import tempfile
import pytest

@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Point the DB at a temp file and initialise it."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("DB_PATH", db_path)
    # Clear the lru_cache so Settings picks up the monkeypatched env var
    from xarchiver.config import get_settings
    get_settings.cache_clear()
    from xarchiver import db as dbmod
    if hasattr(dbmod._local, "conn"):
        dbmod._local.conn = None
    dbmod.init_db()
    yield db_path
    if hasattr(dbmod._local, "conn") and dbmod._local.conn:
        dbmod._local.conn.close()
        dbmod._local.conn = None
    get_settings.cache_clear()
