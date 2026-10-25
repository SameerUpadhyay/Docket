import cv2
from .image_preprocessor import decode

def extract_qr_payloads_from_images(images):
    detector=cv2.QRCodeDetector(); payloads=[]
    for content in images:
        image=decode(content)
        variants=[image,cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)]
        for variant in variants:
            try:
                ok,decoded,_,_=detector.detectAndDecodeMulti(variant)
                if ok: payloads.extend(x.strip() for x in decoded if x and x.strip())
                single,_,_=detector.detectAndDecode(variant)
                if single.strip(): payloads.append(single.strip())
            except cv2.error: continue
    return list(dict.fromkeys(payloads))
