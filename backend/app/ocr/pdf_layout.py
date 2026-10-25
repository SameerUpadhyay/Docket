"""Native PDF text, measured words and ruled grids, including complex scripts."""
def extract_layout(content):
    import pymupdf
    pages=[]
    with pymupdf.open(stream=content,filetype='pdf') as document:
        for number,page in enumerate(document,1):
            words=[]
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    spans=line.get('spans',[])
                    text=''.join(span['text'] for span in spans)
                    if not text.strip(): continue
                    rectangle=pymupdf.Rect(line['bbox'])
                    if page.rotation: rectangle=rectangle*page.rotation_matrix
                    words.append({'text':text,'confidence':None,'bbox':{'left':max(0,rectangle.x0/page.rect.width),'top':max(0,rectangle.y0/page.rect.height),'width':rectangle.width/page.rect.width,'height':rectangle.height/page.rect.height},'provenance':'native-text'})
            tables=[table.extract() for table in page.find_tables().tables]
            pages.append({'page':number,'text':page.get_text('text',sort=True),'words':words,'tables':tables})
    return pages
