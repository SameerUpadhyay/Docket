"""One-off ECS initialization; only this task can read the RDS master password.

Run with service desiredCount=0. The ordinary API/worker role is not superuser and
cannot read the master secret. Re-running deliberately does not rotate passwords.
"""
import os
import psycopg
from psycopg import sql

def initialize():
    host=os.environ['DB_HOST']; name=os.getenv('DB_NAME','docket'); user=os.environ['DB_USER']; password=os.environ['DB_PASSWORD']
    with psycopg.connect(host=host,dbname=name,user='docket_admin',password=os.environ['BOOTSTRAP_PASSWORD'],sslmode='verify-full',sslrootcert=os.getenv('DATABASE_SSLROOTCERT','/service/rds-ca.pem')) as db:
        exists=db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(user,)).fetchone()
        if not exists: db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(user),sql.Literal(password)))
        db.execute(sql.SQL('GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}').format(sql.Identifier(name),sql.Identifier(user)))
        db.execute(sql.SQL('GRANT USAGE, CREATE ON SCHEMA public TO {}').format(sql.Identifier(user)))
    print('Restricted application database role initialized. No credentials printed.')

if __name__=='__main__': initialize()
