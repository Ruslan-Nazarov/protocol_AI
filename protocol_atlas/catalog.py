"""Build a lossless, versioned catalog; no model calls or source mutations.

Run from the repository root: py -3 -m protocol_atlas.catalog
The catalog describes source text, not an executable interpretation of its rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


SCHEMA_VERSION = 1
REQUIRED_SOURCES = (
    "PROTOCOL.md",
    "memory/STATE.md",
    "memory/DECISIONS.md",
    "memory/OPEN_QUESTIONS.md",
    "memory/GLOSSARY.md",
    "memory/READER.md",
    "memory/CALIBRATION.md",
    "memory/ARCHITECTURES.md",
    "memory/ERRORS.md",
    "check_answer.py",
    "docs/LAB_CONTRACT.md",
)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")
LIST_ITEM = re.compile(r"^(?:[-+*]|\d+[.)])[ \t]+")
SEPARATOR = re.compile(r"^[ ]{0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _kind(line: str) -> str:
    stripped = line.rstrip("\r\n")
    if not stripped.strip():
        return "blank"
    if HEADING.match(stripped):
        return "heading"
    if FENCE.match(stripped):
        return "code"
    if SEPARATOR.match(stripped):
        return "separator"
    if stripped.lstrip().startswith("|"):
        return "table"
    if LIST_ITEM.match(stripped):
        return "list_item"
    return "paragraph"


def parse_document(path: str, raw: bytes) -> dict:
    """Preserve every character, including line endings and fenced examples.

    This is a source slicer for the repository's Markdown, not a full Markdown
    renderer. Nested list continuations stay in their parent source block.
    Block IDs are local to a document revision; use sha256 with every reference.
    """
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    blocks: list[dict] = []
    sections: list[dict] = []
    stack: list[dict] = []
    position = 0

    def append_block(start: int, end: int, kind: str) -> None:
        blocks.append({
            "id": f"{path}:L{start + 1}",
            "kind": kind,
            "start_line": start + 1,
            "end_line": end,
            "section_id": stack[-1]["id"] if stack else None,
            "text": "".join(lines[start:end]),
        })

    while position < len(lines):
        start = position
        visible = lines[position].rstrip("\r\n")
        if position == 0:
            visible = visible.removeprefix("\ufeff")
        kind = _kind(visible) if path.endswith(".md") else "code"
        if not path.endswith(".md"):
            position = len(lines)
        elif kind == "heading":
            match = HEADING.match(visible)
            assert match is not None
            level, title = len(match[1]), match[2]
            while stack and stack[-1]["level"] >= level:
                stack.pop()["end_line"] = start
            section = {
                "id": f"{path}:S{start + 1}",
                "title": title,
                "level": level,
                "start_line": start + 1,
                "end_line": len(lines),
                "parent_id": stack[-1]["id"] if stack else None,
            }
            sections.append(section)
            stack.append(section)
            position += 1
        elif kind == "code":
            opener = FENCE.match(visible)
            assert opener is not None
            closing = re.compile(r"^[ ]{0,3}" + re.escape(opener[1][0])
                                 + "{" + str(len(opener[1])) + r",}[ \t]*$")
            position += 1
            while position < len(lines):
                candidate = lines[position].rstrip("\r\n")
                position += 1
                if closing.match(candidate):
                    break
        elif kind == "separator":
            position += 1
        else:
            position += 1
            while position < len(lines):
                next_kind = _kind(lines[position])
                if kind == "list_item":
                    # A new top-level item starts a new block. Indented children
                    # and ordinary wrapped continuation text stay with this item.
                    if next_kind != "paragraph":
                        break
                elif next_kind != kind:
                    break
                position += 1
        append_block(start, position, kind)

    document = {
        "path": path,
        "sha256": digest(raw),
        "byte_count": len(raw),
        "line_count": len(lines),
        "media_type": "text/markdown" if path.endswith(".md") else "text/x-python",
        "sections": sections,
        "blocks": blocks,
        "coverage": {"scope": "source_text", "complete": True,
                     "semantic_rule_inventory": "not_reviewed"},
    }
    validate_document(document, raw)
    return document


def validate_document(document: dict, raw: bytes) -> None:
    """Reject gaps, overlaps, altered text and references outside the document."""
    if digest(raw) != document["sha256"]:
        raise ValueError(f"Source revision mismatch: {document['path']}")
    lines = raw.decode("utf-8").splitlines(keepends=True)
    cursor = 1
    section_ids = {s["id"] for s in document["sections"]}
    for block in document["blocks"]:
        end = block["end_line"]
        if block["start_line"] != cursor or end < cursor or end > len(lines):
            raise ValueError(f"Non-contiguous coverage: {block['id']}")
        if block["text"] != "".join(lines[cursor - 1:end]):
            raise ValueError(f"Changed source text: {block['id']}")
        if block["section_id"] is not None and block["section_id"] not in section_ids:
            raise ValueError(f"Missing section: {block['id']}")
        cursor = end + 1
    rebuilt = "".join(b["text"] for b in document["blocks"]).encode("utf-8")
    if cursor != len(lines) + 1 or rebuilt != raw:
        raise ValueError(f"Incomplete coverage: {document['path']}")


def _source_paths(root: Path) -> list[str]:
    paths = set(REQUIRED_SOURCES)
    paths.update(p.relative_to(root).as_posix() for p in (root / "memory").glob("*.md"))
    for relative in paths:
        candidate = root / relative
        if not candidate.resolve().is_relative_to(root):
            raise ValueError(f"Source escapes project root: {relative}")
        if not candidate.is_file():
            raise FileNotFoundError(f"Required source missing: {relative}")
    return sorted(paths)


def _annotations(root: Path, documents: list[dict], strict: bool = True) -> list[dict]:
    """Resolve editorial notes to exact, unique excerpts of current sources."""
    path = root / "atlas" / "annotations.json"
    if not path.is_file():
        raise FileNotFoundError("Required atlas metadata missing: atlas/annotations.json")
    entries = json.loads(path.read_text(encoding="utf-8"))
    by_path = {d["path"]: d for d in documents}
    seen: set[str] = set()
    resolved = []
    for entry in entries:
        if entry["id"] in seen:
            raise ValueError(f"Duplicate annotation: {entry['id']}")
        seen.add(entry["id"])
        refs = []
        warnings = []
        for selector in entry["sources"]:
            document = by_path[selector["path"]]
            text = "".join(b["text"] for b in document["blocks"])
            quote = selector["quote"]
            if not quote or text.count(quote) != 1:
                if strict:
                    raise ValueError(f"Excerpt missing or ambiguous: {entry['id']}: {selector['path']}")
                warnings.append(selector['path'])
                continue
            offset = text.index(quote)
            start = text[:offset].count("\n") + 1
            end = start + quote.count("\n")
            refs.append({**selector, "sha256": document["sha256"],
                         "start_line": start, "end_line": end})
        resolved.append({**entry, "sources": [] if warnings else refs,
                         **({'source_warnings': warnings,
                             'body': 'Цитата редакторского пояснения изменилась или стала неоднозначной; ссылка требует обновления. ' + entry['body']} if warnings else {})})
    return resolved


def build_catalog(root: Path, strict_annotations: bool = True) -> dict:
    root = root.resolve()
    documents = [parse_document(path, (root / path).read_bytes())
                 for path in _source_paths(root)]
    annotations = _annotations(root, documents, strict_annotations)
    signature = json.dumps({"documents": [(d["path"], d["sha256"]) for d in documents],
                            "annotations": annotations}, ensure_ascii=False, sort_keys=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_revision": digest(signature.encode("utf-8")),
        "documents": documents,
        "annotations": annotations,
        "coverage": {
            "scope": "PROTOCOL.md, memory/*.md, check_answer.py, docs/LAB_CONTRACT.md",
            "source_text_complete": True,
            "semantic_rule_inventory": "not_reviewed",
            "documents": len(documents),
            "lines": sum(d["line_count"] for d in documents),
            "sections": sum(len(d["sections"]) for d in documents),
            "blocks": sum(len(d["blocks"]) for d in documents),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    catalog = build_catalog(root)
    output = root / "build" / "catalog.json"
    if not output.resolve().is_relative_to(root):
        raise ValueError("Catalog output escapes project root")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Replace only a derived build artifact, after all validation has passed.
    pending = output.with_suffix(".json.tmp")
    if pending.is_symlink():
        raise ValueError("Temporary catalog output must not be a symlink")
    pending.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(output)
    print(json.dumps({"output": str(output), **catalog["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
