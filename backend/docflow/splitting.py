"""DOC534.12: where a scanned stack (one PDF holding several documents) is probably cut. Only a suggestion: nothing here touches a
file, and the person sees the ranges before anything is split."""
from .analyze import DocumentAnalyzer


def suggest(pages: list[str], blank: list[int], analyzer: DocumentAnalyzer) -> list[tuple[int, int]]:
    """The page ranges (from 1, both ends included) of the documents in the stack, or [] when it looks like ONE document.
    A new document starts at a sheet that follows a blank separator, or at a page that names another company than the document being
    read, or carries another invoice number. A page that names no company (the second page of an invoice) belongs to the document
    before it. The blank separators are left out of every range.
    A date is not a cut point: the later pages of a statement list many."""
    parts: list[tuple[int, int]] = []
    start, last = 0, 0  # the open document: its first and last page (0 = none open)
    company = number = None  # what the open document has said about itself so far
    for i, text in enumerate(pages, 1):
        if i in blank:  # a separator: the document before it is over, the next sheet opens another
            if start:
                parts.append((start, last))
            start = last = 0
            company = number = None
            continue
        a = analyzer.analyze(text) if text.strip() else None
        found = (a.company or "").casefold() if a else ""
        n = a.invoice_number if a else None
        if start and ((found and company and found != company) or (n and number and n != number)):
            parts.append((start, last))
            start, company, number = 0, None, None
        if not start:
            start = i
        last = i
        company, number = company or found or None, number or n
    if start:
        parts.append((start, last))
    return parts if len(parts) > 1 else []
