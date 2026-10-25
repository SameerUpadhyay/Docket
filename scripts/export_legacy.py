#!/usr/bin/env python3
"""Local owner recovery of the prototype's encrypted, unassigned archive.

Exports to a new private ZIP. It never attaches old records to a new account.
"""
import argparse,base64,json,os,sys
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.models import database as db
p=argparse.ArgumentParser(); p.add_argument('destination',type=Path); args=p.parse_args()
if args.destination.exists(): p.error('Choose a new destination; this command never overwrites an export.')
db.migrate()
with db.connect() as tx: rows=tx.execute('SELECT kind,payload FROM legacy_archive ORDER BY id').fetchall()
output=BytesIO(); index=[]
with ZipFile(output,'w',ZIP_DEFLATED) as archive:
    for number,row in enumerate(rows):
        record=json.loads(db.unseal(row['payload']))
        if row['kind']=='notice': archive.writestr(f'notices/{number+1}.json',json.dumps(record,indent=2))
        else:
            path=f'evidence/{number+1}.bin'; archive.writestr(path,base64.b64decode(record.pop('content')))
            index.append(record|{'path':path})
    archive.writestr('evidence/index.json',json.dumps(index,indent=2))
    archive.writestr('README.txt','Recovered prototype records. Confirm ownership and originals before importing into any business account. This ZIP contains private data; protect it.\n')
fd=os.open(args.destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as stream: stream.write(output.getvalue())
print(f'Recovered {len(rows)} encrypted legacy records to a private ZIP. No account was modified.')
