"""Conservative reversible geometry. Source pixels are never overwritten."""
from dataclasses import dataclass
from io import BytesIO
import cv2,numpy as np
from PIL import Image,ImageOps
cv2.setNumThreads(1)

@dataclass
class PreparedImage:
    source:bytes
    enhanced:bytes
    width:int
    height:int
    angle:float
    sharpness:float
    transform:np.ndarray
    perspective_corrected:bool=False

def decode(content):
    with Image.open(BytesIO(content)) as source:
        if source.width*source.height>30_000_000: raise ValueError('Image exceeds 30 megapixels')
        image=ImageOps.exif_transpose(source).convert('RGB')
        return cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2BGR)
def encoded(image):
    ok,buffer=cv2.imencode('.png',image)
    if not ok: raise ValueError('Image encoding failed')
    return buffer.tobytes()
def prepare(content):
    image=decode(content); height,width=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    source_gray=gray.copy(); perspective=np.eye(3); corrected=False
    contours,_=cv2.findContours(cv2.Canny(cv2.GaussianBlur(gray,(5,5),0),50,150),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:5]:
        if cv2.contourArea(contour)<width*height*.75: continue
        quad=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
        if len(quad)!=4 or not cv2.isContourConvex(quad): continue
        points=quad.reshape(4,2).astype(np.float32)
        sums=points.sum(axis=1); differences=np.diff(points,axis=1).ravel()
        ordered=np.array([points[np.argmin(sums)],points[np.argmin(differences)],points[np.argmax(sums)],points[np.argmax(differences)]],np.float32)
        if len(np.unique(ordered,axis=0))!=4: continue
        target_w=int(max(np.linalg.norm(ordered[1]-ordered[0]),np.linalg.norm(ordered[2]-ordered[3])))
        target_h=int(max(np.linalg.norm(ordered[3]-ordered[0]),np.linalg.norm(ordered[2]-ordered[1])))
        if target_w<200 or target_h<200: continue
        perspective=cv2.getPerspectiveTransform(ordered,np.array([[0,0],[target_w-1,0],[target_w-1,target_h-1],[0,target_h-1]],np.float32))
        image=cv2.warpPerspective(image,perspective,(target_w,target_h),borderValue=(255,255,255)); gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY); corrected=True; break
    work_h,work_w=gray.shape
    sharpness=round(float(cv2.Laplacian(source_gray,cv2.CV_64F).var()),2)
    # Hough lines vote only for small skew. Table borders and shirorekha share the
    # same page tilt; a median protects against a single signature/stamp.
    small=cv2.resize(gray,(0,0),fx=min(1,1600/work_w),fy=min(1,1600/work_w))
    edges=cv2.Canny(small,60,180)
    lines=cv2.HoughLinesP(edges,1,np.pi/1800,threshold=70,minLineLength=max(40,small.shape[1]//12),maxLineGap=12)
    angles=[]
    if lines is not None:
        for x1,y1,x2,y2 in lines.reshape(-1,4):
            angle=np.degrees(np.arctan2(y2-y1,x2-x1))
            if abs(angle)<=15: angles.append(angle)
    angle=float(np.median(angles)) if len(angles)>=4 else 0.
    if abs(angle)<.4: angle=0.
    transform=cv2.getRotationMatrix2D((work_w/2,work_h/2),angle,1)
    if angle:
        # Expand the canvas; crop-free deskew protects edge dates and references.
        sine,cosine=abs(transform[0,1]),abs(transform[0,0])
        new_width=int(np.ceil(work_w*cosine+work_h*sine)); new_height=int(np.ceil(work_h*cosine+work_w*sine))
        transform[0,2]+=(new_width-work_w)/2; transform[1,2]+=(new_height-work_h)/2
        working=cv2.warpAffine(image,transform,(new_width,new_height),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))
    else: working=image.copy()
    lab=cv2.cvtColor(working,cv2.COLOR_BGR2LAB); l,a,b=cv2.split(lab)
    enhanced=cv2.cvtColor(cv2.merge((cv2.createCLAHE(clipLimit=2.,tileGridSize=(8,8)).apply(l),a,b)),cv2.COLOR_LAB2BGR)
    return PreparedImage(content,encoded(enhanced),width,height,round(angle,3),sharpness,np.vstack((transform,[0,0,1]))@perspective,corrected)
def deskew_and_enhance_document(content):
    prepared=prepare(content)
    # A sharpness statistic is not an accuracy percentage.
    return prepared.enhanced,prepared.angle,prepared.sharpness

def stamp_suppressed_variant(content):
    # Optional second-pass candidate only. Never replace source/primary text: blue
    # ink can itself be a date, signature or legally material annotation.
    image=decode(content); hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([85,60,30]),np.array([165,255,255]))
    image[mask>0]=255
    return encoded(image)
