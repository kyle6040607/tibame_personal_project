from io import BytesIO
from pypdf import PdfReader


def extract_text_from_file(file_name: str, content_bytes: bytes):
    lower_name = file_name.lower()

    if lower_name.endswith(".txt"):
        return content_bytes.decode("utf-8", errors="ignore")

    if lower_name.endswith(".pdf"):
        pdf_stream = BytesIO(content_bytes)
        reader = PdfReader(pdf_stream)

        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text

    return None