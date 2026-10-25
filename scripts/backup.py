#!/usr/bin/env python3
"""Encrypted local SQLite backups with restore verification; Postgres uses pg_dump.

Never place DATA_ENCRYPTION_KEY inside the backup directory. This is an operator
command, not an HTTP endpoint. Restoring requires a new empty destination.
"""
import argparse,sqlite3,sys
from pathlib import Path
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app import config
from app.models import database as db
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['backup','restore','verify'])
parser.add_argument('path',type=Path)
parser.add_argument('--destination',type=Path)
args=parser.parse_args()
if config.DATABASE_URL: parser.error('For PostgreSQL use the documented encrypted pg_dump / pg_restore process.')
if args.action=='backup':
    if args.path.exists(): parser.error('Backup path exists; choose a new name.')
    import tempfile,os
    with tempfile.TemporaryDirectory(prefix='docket-backup-') as folder:
        copy=Path(folder)/'snapshot.sqlite3'
        with sqlite3.connect(config.DATABASE_PATH) as original,sqlite3.connect(copy) as target: original.backup(target)
        encrypted=db.cipher().encrypt(copy.read_bytes())
    fd=os.open(args.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as output: output.write(encrypted)
    print('Encrypted backup written. Keep its encryption key in a separate secret store.')
else:
    import tempfile,os
    data=db.cipher().decrypt(args.path.read_bytes())
    with tempfile.TemporaryDirectory(prefix='docket-restore-check-') as folder:
        restored=Path(folder)/'check.sqlite3'; restored.write_bytes(data)
        with sqlite3.connect(restored) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise SystemExit('Backup integrity check failed.')
            check.execute('SELECT version FROM schema_migrations').fetchall()
    if args.action=='restore':
        if not args.destination or args.destination.exists(): parser.error('Restore requires --destination pointing to a new file.')
        fd=os.open(args.destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream: stream.write(data)
        print('Restored to a new file. Replay deletion records and revoke restored sessions before opening the service.')
    else: print('Backup decrypted and SQLite integrity verified.')
