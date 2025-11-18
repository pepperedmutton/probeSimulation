from PyPDF2 import PdfReader
reader = PdfReader("Chen210R.pdf")
start = 2
end = 20
for i in range(start-1, min(end, len(reader.pages))):
    text = reader.pages[i].extract_text() or ''
    print(f'--- PAGE {i+1} ---')
    print(text)
