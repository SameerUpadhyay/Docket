"""Measured ruled-table cells; no assumptions about column order or missing amounts."""
import cv2,numpy as np
from .image_preprocessor import decode

def _clusters(values,gap=6):
    groups=[]
    for value in values:
        if not groups or value-groups[-1][-1]>gap: groups.append([value])
        else: groups[-1].append(value)
    return [int(np.median(group)) for group in groups]

def _regions(horizontal,vertical,width):
    # Printed HTML/office tables can have narrowly separated cell borders.
    # Join only the detection mask, never source pixels or recognized values.
    gap=max(6,round(width*.006))
    connected=cv2.morphologyEx(cv2.bitwise_or(horizontal,vertical),cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(gap+3,gap+3)))
    contours,_=cv2.findContours(connected,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    return contours,gap

def extract_ruled_tables(content,words):
    image=decode(content); gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY); height,width=gray.shape
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,13)
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(35,width//16),1)))
    vertical=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(25,height//50))))
    contours,gap=_regions(horizontal,vertical,width)
    tables=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w<width*.3 or h<height*.025: continue
        xs=_clusters(np.flatnonzero(np.sum(vertical[y:y+h,x:x+w]>0,axis=0)>h*.55)+x,gap)
        ys=_clusters(np.flatnonzero(np.sum(horizontal[y:y+h,x:x+w]>0,axis=1)>w*.7)+y,gap)
        if not (3<=len(xs)<=20 and 3<=len(ys)<=100): continue
        grid=[]
        for top,bottom in zip(ys,ys[1:]):
            row=[]
            for left,right in zip(xs,xs[1:]):
                selected=[]
                for word in words:
                    b=word.get('bbox',{}); cx=b.get('left',-999)+b.get('width',0)/2; cy=b.get('top',-999)+b.get('height',0)/2
                    if left<cx<right and top<cy<bottom: selected.append(word)
                selected.sort(key=lambda word:(round(word['bbox']['top']/8),word['bbox']['left']))
                row.append(' '.join(word['text'] for word in selected) or None)
            grid.append(row)
        tables.append(grid)
    return tables


def recover_grid_text(content,recognize):
    """A second OCR pass on measured table regions after border-only suppression.

    The original page and primary transcript are unchanged. Glyphs outside table
    borders (including Devanagari connectors) are never globally erased.
    """
    from .image_preprocessor import encoded
    image=decode(content); gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY); height,width=gray.shape
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,13)
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(35,width//16),1)))
    vertical=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(25,height//50))))
    lines=cv2.bitwise_or(horizontal,vertical)
    contours,gap=_regions(horizontal,vertical,width)
    recovered=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w<width*.3 or h<height*.025: continue
        xs=_clusters(np.flatnonzero(np.sum(vertical[y:y+h,x:x+w]>0,axis=0)>h*.55)+x,gap)
        ys=_clusters(np.flatnonzero(np.sum(horizontal[y:y+h,x:x+w]>0,axis=1)>w*.7)+y,gap)
        if len(xs)<3 or len(ys)<3: continue
        pad=12; left=max(0,x-pad);top=max(0,y-pad);right=min(width,x+w+pad);bottom=min(height,y+h+pad)
        crop=image[top:bottom,left:right].copy(); mask=lines[top:bottom,left:right]
        clean=cv2.inpaint(crop,mask,2,cv2.INPAINT_TELEA)
        result=recognize(encoded(clean))
        words=result.get('words',[])
        for word in words:
            word['bbox']['left']+=left; word['bbox']['top']+=top
        for grid in extract_ruled_tables(content,words):
            from .anchor_extractor import money
            attempts=0
            for row_index,row in enumerate(grid[1:],1):
                for column,value in enumerate(row[1:],1):
                    if money(value) is not None or attempts>=6: continue
                    # Only a measured cell under a recognizable numeric header
                    # receives numeric-only OCR; a blank cell is never zero-filled.
                    import re
                    if column>=len(grid[0]) or not re.search(r'tax|interest|penalty|fee|total|कर|ब्याज|दंड|कुल',str(grid[0][column] or ''),re.I): continue
                    if row_index+1>=len(ys) or column+1>=len(xs): continue
                    attempts+=1
                    cell=image[ys[row_index]+5:ys[row_index+1]-5,xs[column]+5:xs[column+1]-5]
                    if not cell.size: continue
                    reread=recognize(encoded(cell),numeric=True)
                    candidate=re.sub(r'\s+','',reread.get('text',''))
                    confidence=[word.get('confidence',0) or 0 for word in reread.get('words',[])]
                    if money(candidate) is not None and confidence and min(confidence)>=80: row[column]=candidate
            recovered.append(grid)
    return recovered
