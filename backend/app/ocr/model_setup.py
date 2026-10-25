"""Download only official, SHA-256-locked local OCR models; no runtime documents."""
import argparse,hashlib,json,ssl,tempfile,urllib.request
from pathlib import Path
import certifi

def install(destination):
    destination.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(Path(__file__).with_name('models.lock.json').read_text())
    for language,item in manifest.items():
        target=destination/(language+'.traineddata')
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']: continue
        with urllib.request.urlopen(item['url'],context=ssl.create_default_context(cafile=certifi.where()),timeout=60) as response:
            data=response.read(40*1024*1024)
        if hashlib.sha256(data).hexdigest()!=item['sha256']: raise RuntimeError('OCR model checksum mismatch; installation stopped.')
        temporary=target.with_suffix('.download');temporary.write_bytes(data);temporary.chmod(0o644);temporary.replace(target)
    print('English/Hindi OCR models match the committed SHA-256 manifest.')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True,type=Path);install(parser.parse_args().destination)
