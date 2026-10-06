import copy
import json
import re
from pathlib import Path
import tempfile
import unittest

from protocol_atlas.catalog import REQUIRED_SOURCES, build_catalog, parse_document, validate_document


ROOT = Path(__file__).resolve().parents[1]


class DocumentTests(unittest.TestCase):
    def test_fenced_headings_are_examples_not_sections(self):
        raw = ("# Текст\r\n\r\n```md\r\n## D-NNN пример\r\n```\r\n"
               "## Правило\r\n1. Первый\r\n2. Второй\r\n  продолжение\r\n").encode()
        doc = parse_document("test.md", raw)
        self.assertEqual([s["title"] for s in doc["sections"]], ["Текст", "Правило"])
        self.assertEqual(sum(b["kind"] == "list_item" for b in doc["blocks"]), 2)
        self.assertEqual("".join(b["text"] for b in doc["blocks"]).encode(), raw)

    def test_long_fence_needs_matching_closer(self):
        doc = parse_document("test.md", b"````\n```\n# inside\n````\n# outside\n")
        self.assertEqual([s["title"] for s in doc["sections"]], ["outside"])

    def test_empty_bom_unclosed_fence_and_no_final_newline(self):
        for raw in (b"", "\ufeff# Начало\nтекст".encode(), b"~~~\n# example", b"# Last"):
            with self.subTest(raw=raw):
                validate_document(parse_document("test.md", raw), raw)

    def test_section_parent_and_ranges(self):
        doc = parse_document("test.md", b"# A\n## B\ntext\n## C\n### D\nlast\n")
        a, b, c, d = doc["sections"]
        self.assertEqual(b["end_line"], 3)
        self.assertEqual(c["parent_id"], a["id"])
        self.assertEqual(d["parent_id"], c["id"])
        self.assertEqual(a["end_line"], 6)

    def test_tables_and_python_are_preserved(self):
        doc = parse_document("test.md", b"| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertEqual(len(doc["blocks"]), 1)
        self.assertEqual(doc["blocks"][0]["kind"], "table")
        code = parse_document("test.py", b"# Not a heading\nprint('hello')\n")
        self.assertEqual(code["sections"], [])

    def test_missing_changed_overlapping_and_stale_content_rejected(self):
        raw = b"# Title\n\nBody\n"
        original = parse_document("test.md", raw)
        missing = copy.deepcopy(original)
        missing["blocks"].pop()
        changed = copy.deepcopy(original)
        changed["blocks"][-1]["text"] = "Different\n"
        overlap = copy.deepcopy(original)
        overlap["blocks"][-1]["start_line"] = 1
        for invalid in (missing, changed, overlap):
            with self.assertRaises(ValueError):
                validate_document(invalid, raw)
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            validate_document(original, raw + b"new\n")


class CatalogTests(unittest.TestCase):
    def fixture(self, root):
        for relative in REQUIRED_SOURCES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Example\n", encoding="utf-8")
        (root / "atlas").mkdir()
        (root / "atlas/annotations.json").write_text("[]", encoding="utf-8")

    def test_missing_required_file_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                build_catalog(Path(temp))

    def test_new_memory_document_included(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / "memory/NEW.md").write_text("new evidence", encoding="utf-8")
            catalog = build_catalog(root)
            self.assertIn("memory/NEW.md", [d["path"] for d in catalog["documents"]])

    def test_annotation_must_resolve_uniquely(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            annotation = [{"id": "note", "sources": [{"path": "PROTOCOL.md", "quote": "missing"}]}]
            (root / "atlas/annotations.json").write_text(json.dumps(annotation), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                build_catalog(root)
            annotation[0]["sources"][0]["quote"] = "Example"
            (root / "atlas/annotations.json").write_text(json.dumps(annotation), encoding="utf-8")
            (root / "PROTOCOL.md").write_text("Example Example", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                build_catalog(root)

    def test_revision_changes_when_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            before = build_catalog(root)
            (root / "memory/STATE.md").write_text("# New state", encoding="utf-8")
            after = build_catalog(root)
            self.assertNotEqual(before["catalog_revision"], after["catalog_revision"])

    def test_real_catalog_is_complete_repeatable_and_read_only(self):
        source_paths = [ROOT / p for p in REQUIRED_SOURCES]
        before = {str(p): p.read_bytes() for p in source_paths}
        catalog = build_catalog(ROOT)
        self.assertEqual(catalog, build_catalog(ROOT))
        self.assertEqual(before, {str(p): p.read_bytes() for p in source_paths})
        self.assertTrue(catalog["coverage"]["source_text_complete"])
        self.assertEqual(catalog["coverage"]["semantic_rule_inventory"], "not_reviewed")
        for doc in catalog["documents"]:
            validate_document(doc, (ROOT / doc["path"]).read_bytes())
        protocol = next(d for d in catalog["documents"] if d["path"] == "PROTOCOL.md")
        self.assertFalse(any(s["title"].startswith("D-NNN") for s in protocol["sections"]))
        self.assertEqual(len(catalog["annotations"]), 6)

    def test_protocol_numbers_and_interface_references_resolve(self):
        protocol = next(d for d in build_catalog(ROOT)['documents'] if d['path'] == 'PROTOCOL.md')
        self.assertEqual([int(s['title'].split('.')[0]) for s in protocol['sections'] if s['level'] == 2],
                         list(range(1, 11)))
        labels = {s['title'].split()[0] for s in protocol['sections']}
        previous = next(d for d in build_catalog(ROOT)['documents'] if d['path'] == 'memory/REGULATOR_PREVIOUS.md')
        previous_labels = {s['title'].split()[0] for s in previous['sections']}
        for section in protocol['sections']:
            if section['level'] == 3:
                parent = next(s for s in protocol['sections'] if s['id'] == section['parent_id'])
                self.assertEqual(section['title'].split('.')[0], parent['title'].split('.')[0])
        app = (ROOT / 'protocol_atlas/web/app.js').read_text(encoding='utf-8')
        for label in re.findall(r"(?:sectionButton|findSection)\([^\n]*?['\"](\d+(?:\.\d+)*\.?)['\"]", app):
            with self.subTest(label=label):
                self.assertIn(label, labels)

    def test_renumbered_rules_keep_their_mechanisms_and_lab_sources(self):
        from protocol_atlas.requirements import inventory
        from protocol_atlas.laboratory import episode
        requirements = inventory(ROOT)
        self.assertTrue(requirements['coverage']['complete'])
        for label, path in [('10.1', 'protocol_atlas/memory.py'),
                            ('6.3', 'check_answer.py'), ('9.3', 'protocol_atlas/adaptive.py')]:
            with self.subTest(label=label):
                cards = [c for c in requirements['cards'] if c['section'].startswith(label + ' ')]
                self.assertTrue(cards)
                self.assertTrue(all(c['mechanism']['path'] == path for c in cards))
        sources_by_rule={'2.2':'protocol_atlas/context.py','2.3':'protocol_atlas/logic.py','5.2':'protocol_atlas/runtime_rules.py'}
        for label,path in sources_by_rule.items():
            cards=[c for c in requirements['cards'] if c['section'].startswith(label+' ')]
            self.assertTrue(cards)
            self.assertTrue(all(c['mechanism']['path']==path for c in cards))
        sources = episode(ROOT)['sources']
        for path, labels in [('PROTOCOL.md', ('9.3', '10.1')),
                             ('memory/REGULATOR_PREVIOUS.md', ('2.5', '2.7'))]:
            text = '\n'.join(source['text'] for source in sources if source['path'] == path)
            for label in labels:
                self.assertRegex(text, r'(?m)^### ' + re.escape(label) + ' ')


if __name__ == "__main__":
    unittest.main()
