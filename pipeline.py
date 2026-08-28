import argparse
from ingest.extractor import extract_text
from extract.cv_parser import parse_cv
from db.candidates_repo import save_candidate


def process_cv(path: str) -> int:
    text, method = extract_text(path, with_method=True)
    candidate = parse_cv(text, source_is_ocr=(method == "ocr"))
    candidate_id = save_candidate(candidate, source_method=method, raw_text=text)
    return candidate_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a CV: extract and store it.")
    parser.add_argument("path", help="Path to the CV file")
    args = parser.parse_args()

    cid = process_cv(args.path)
    print(f"✅ Candidate saved with id={cid}")