"""Private optional S3 object storage. Content is application-encrypted before upload.

Database rows hold object references; downloads are streamed through authorized API
handlers. An outbox makes post-transaction object deletion retryable.
"""
import os,uuid
from app import config

def configured(): return bool(os.getenv('OBJECT_BUCKET'))
def client():
    import boto3
    return boto3.client('s3',region_name=os.getenv('AWS_REGION','ap-south-1'),endpoint_url=os.getenv('S3_ENDPOINT_URL') or None)
def put(encrypted,workspace):
    key=f'private/{workspace}/{uuid.uuid4().hex}'
    options={'ServerSideEncryption':'aws:kms','SSEKMSKeyId':os.environ['OBJECT_KMS_KEY_ID']} if os.getenv('OBJECT_KMS_KEY_ID') else {'ServerSideEncryption':'AES256'}
    client().put_object(Bucket=os.environ['OBJECT_BUCKET'],Key=key,Body=encrypted.encode(),ContentType='application/octet-stream',**options)
    return 's3:'+key

def get(reference):
    response=client().get_object(Bucket=os.environ['OBJECT_BUCKET'],Key=reference[3:])
    with response['Body'] as stream: return stream.read(16*1024*1024).decode()

def queue_delete(tx,reference):
    if reference.startswith('s3:'): tx.execute('INSERT INTO object_deletions VALUES (?,0) ON CONFLICT(key) DO NOTHING',(reference[3:],))

def collect():
    from app.models import database as db
    with db.connect() as tx: rows=tx.execute('SELECT key FROM object_deletions LIMIT 100').fetchall()
    for row in rows:
        try:
            client().delete_object(Bucket=os.environ['OBJECT_BUCKET'],Key=row['key'])
            with db.connect() as tx: tx.execute('DELETE FROM object_deletions WHERE key=?',(row['key'],))
        except Exception:
            with db.connect() as tx: tx.execute('UPDATE object_deletions SET attempts=attempts+1 WHERE key=?',(row['key'],))
