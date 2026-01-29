import pytest
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import create_engine, get_session, Base
from modules.extraction.pipeline import ExtractionContext

@pytest.fixture
def mock_db_session():
    """Creates an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = get_session(engine)
    yield session
    session.close()

@pytest.fixture
def sample_bytes():
    """Returns dummy PDF bytes."""
    return b"%PDF-1.4 header dummy content"

@pytest.fixture
def mock_context(sample_bytes):
    """Returns a fresh ExtractionContext."""
    return ExtractionContext(
        file_bytes=sample_bytes,
        file_hash="dummy_hash_123"
    )
