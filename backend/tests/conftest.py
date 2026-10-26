import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# Each test run uses an isolated database, never the user's workspace data.
os.environ['DATABASE_PATH']=str(Path(tempfile.mkdtemp(prefix='docket-tests-'))/'test.sqlite3')
os.environ['GEMINI_API_KEY']=''
os.environ['INBOUND_INLINE_WORKER']='0'
os.environ['DOCKET_DEMO_MODE']='1'
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield instance
