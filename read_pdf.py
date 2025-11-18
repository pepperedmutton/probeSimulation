from PyPDF2 import PdfReader
reader = PdfReader("Chen210R.pdf")
for i, page in enumerate(reader.pages, 1):
    text = page.extract_text() or ''
    print(f'--- PAGE {i} ---')
    print(text)
