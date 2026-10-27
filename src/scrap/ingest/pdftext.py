"""A PDF's text layer, read by pypdf in a child process of its own (#234). files.py
runs this file as a script, isolated, with an empty environment and no stderr:

    python -I pdftext.py PATH MAX_PAGES MAX_CHARS MEMORY CPU

(python -m scrap.ingest.pdftext works too, but imports the service's packages first.)
The child caps its own address space at MEMORY bytes and its CPU time at CPU seconds
before it parses anything (in the child, not a preexec_fn: the service has threads),
so a hostile file can cost it its time and memory, not the service's; the CPU cap also
ends a child the service left behind at shutdown. pypdf's logging is off: a broken
file can warn once per operator. It prints {pages, pages_read, text, truncated} as
JSON: the first MAX_PAGES pages, at most MAX_CHARS characters of text; truncated if
either cut it. A PDF encrypted with a password other than the empty one (which pypdf
tries) is not read. Exit status on failure: UNREADABLE, ENCRYPTED or OUT_OF_MEMORY.
"""

import json
import logging
import sys
import warnings
from typing import Any

UNREADABLE = 2
OUT_OF_MEMORY = 3
ENCRYPTED = 4


def extract(path: str, max_pages: int, max_chars: int) -> dict[str, Any]:
    from pypdf import PdfReader  # after the memory cap

    reader = PdfReader(path)  # tries the empty password, as pypdf does
    pages = len(reader.pages)
    parts: list[str] = []
    chars, read, truncated = 0, 0, pages > max_pages
    for page in reader.pages[:max_pages]:
        text = page.extract_text() or ""
        read += 1
        if chars + len(text) > max_chars:
            parts.append(text[: max_chars - chars])
            truncated = True
            break
        parts.append(text)
        chars += len(text) + 1  # the newline between pages
    text = "\n".join(parts).strip()
    return {"pages": pages, "pages_read": read, "text": text, "truncated": truncated}


def limit(memory: int, cpu: int) -> None:
    try:
        import resource
    except ImportError:  # not on POSIX: no caps
        return
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))


def main(argv: list[str]) -> int:
    path, max_pages, max_chars, memory, cpu = argv
    limit(int(memory), int(cpu))
    logging.disable(logging.CRITICAL)  # pypdf's warnings: one per bad operator
    warnings.simplefilter("ignore")
    try:
        out = extract(path, int(max_pages), int(max_chars))
    except MemoryError:
        return OUT_OF_MEMORY
    except Exception as error:  # noqa: BLE001  whatever a bad file makes pypdf raise
        try:
            from pypdf.errors import FileNotDecryptedError, WrongPasswordError
        except MemoryError:
            return OUT_OF_MEMORY
        locked = isinstance(error, FileNotDecryptedError | WrongPasswordError)
        return ENCRYPTED if locked else UNREADABLE
    try:
        json.dump(out, sys.stdout)
    except MemoryError:
        return OUT_OF_MEMORY
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
