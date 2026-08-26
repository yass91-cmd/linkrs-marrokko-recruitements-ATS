import pymupdf

def extract_text_from_pdf(path: str) -> str:
    doc = pymupdf.open(path)          # opens the PDF
    text = ""                      # empty box to collect text
    for page in doc:               # go through each page
        text += page.get_text()    # add that page's text to the box
    doc.close()                    # close the file
    return text                    # hand back everything


if __name__ == "__main__":
    result = extract_text_from_pdf("data/sample_cv.pdf")
    print(result[:500])