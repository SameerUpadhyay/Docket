"""Recover accepted mail after process restarts; run as a supervised service."""
import time,threading
from app import config
from app.models import database as db
from app.email_pipeline import store
from app.email_pipeline.processor import process_next

def main():
    config.validate_production()
    db.migrate(); store.migrate()
    def fetch_inbox():
        from app.email_pipeline.agentmail_receiver import poll_once
        while True:
            try: poll_once()
            except Exception: pass
            time.sleep(15)
    threading.Thread(target=fetch_inbox,daemon=True).start()
    while True:
        try:
            if not process_next(): time.sleep(1)
        except Exception:
            # Never log message content or provider credentials.
            time.sleep(5)

if __name__=='__main__': main()
