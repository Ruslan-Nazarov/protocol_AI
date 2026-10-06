import unittest,tempfile
from pathlib import Path
from protocol_atlas.translations import TranslationStore,write_json
from protocol_atlas.source_editor import SourceConflict
class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'PROTOCOL.md'
        self.source.write_text('# Заголовок\n\nПервый текст.\n\nВторой текст.\n',encoding='utf-8')
        self.store=TranslationStore(self.root)
        doc=self.store.read('PROTOCOL.md')
        for unit in doc['units']:
            unit.update(translation={'# Заголовок\n':'# Title\n','Первый текст.\n':'First text.\n','Второй текст.\n':'Second text.\n'}.get(unit['source'],unit['source']),translated_source=unit['source'],translated_source_sha256=unit['source_sha256'])
        write_json(self.store.target('PROTOCOL.md')[1],{'units':doc['units']})
    def test_source_change_marks_only_changed_unit_and_retains_old_basis(self):
        self.source.write_text('# Заголовок\n\nПервый изменён.\n\nВторой текст.\n',encoding='utf-8')
        doc=self.store.read('PROTOCOL.md');self.assertEqual(doc['pending'],1)
        stale=next(u for u in doc['units'] if u['status']=='stale')
        self.assertEqual(stale['translation'],'First text.\n');self.assertEqual(stale['translated_source'],'Первый текст.\n')
    def test_insertion_does_not_invalidate_existing_translations(self):
        self.source.write_text('# Заголовок\n\nНовый текст.\n\nПервый текст.\n\nВторой текст.\n',encoding='utf-8')
        doc=self.store.read('PROTOCOL.md');self.assertEqual(doc['pending'],1)
        self.assertEqual(next(u for u in doc['units'] if u['source']=='Второй текст.\n')['status'],'current')
    def test_translation_save_is_versioned_and_never_changes_source(self):
        doc=self.store.read('PROTOCOL.md');unit=next(u for u in doc['units'] if u['source']=='Первый текст.\n')
        payload={'path':doc['path'],'unit_id':unit['unit_id'],'revision':doc['revision'],'source_sha256':doc['source_sha256'],'translation':'Revised English.'}
        before=self.source.read_bytes();saved=self.store.save(payload)
        self.assertEqual(self.source.read_bytes(),before);self.assertNotEqual(saved['revision'],doc['revision'])
        self.assertTrue(self.store.history_store.path.is_file())
        self.assertEqual(len(self.store.history('PROTOCOL.md',unit['unit_id'])['versions']),2)
        with self.assertRaises(SourceConflict):self.store.save(payload)
    def test_changed_source_rejects_old_translation_submission(self):
        doc=self.store.read('PROTOCOL.md');self.source.write_text('Другой оригинал.',encoding='utf-8')
        with self.assertRaises(SourceConflict):self.store.save({'path':doc['path'],'unit_id':doc['units'][0]['unit_id'],'revision':doc['revision'],'source_sha256':doc['source_sha256'],'translation':'English'})
    def test_new_interface_message_is_detected_and_can_be_translated(self):
        web=self.root/'protocol_atlas/web';web.mkdir(parents=True)
        (web/'app.js').write_text("const label='Новая подпись';",encoding='utf-8')
        inventory=self.store.ui();self.assertEqual(inventory['pending'],1)
        entry=inventory['entries'][0]
        result=self.store.save_ui({'id':entry['id'],'revision':inventory['revision'],'translation':'New label'})
        self.assertEqual(result['pending'],0)
        (web/'app.js').write_text("const label='Изменённая подпись';",encoding='utf-8')
        self.assertEqual(self.store.ui()['pending'],1)
        with self.assertRaises(SourceConflict):self.store.save_ui({'id':entry['id'],'revision':inventory['revision'],'translation':'Old label'})

    def test_ui_inventory_ignores_comments_and_handles_nested_templates(self):
        from protocol_atlas.ui_messages import ui_sources
        web=self.root/'protocol_atlas/web';web.mkdir(parents=True)
        source="// Не переводить комментарий\nconst a=`<button title=\"Подсказка\">${ok?'Первый':'Второй'}</button>`; const r=/[\"'А-Я]/g;"
        (web/'app.js').write_text(source,encoding='utf-8')
        messages=ui_sources(self.root)
        self.assertIn('Первый',messages);self.assertIn('Второй',messages);self.assertIn('Подсказка',messages)
        self.assertNotIn('Не переводить комментарий',messages)
        self.assertFalse(any('const r=' in message for message in messages))

    def payload(self, text):
        doc=self.store.read('PROTOCOL.md');unit=next(u for u in doc['units'] if u['source'].startswith('Первый'))
        return dict(path=doc['path'],unit_id=unit['unit_id'],revision=doc['revision'],source_sha256=doc['source_sha256'],translation=text)

    def test_unchanged_save_preserves_bytes_and_creates_no_history(self):
        payload=self.payload('First text.\n');target=self.store.target('PROTOCOL.md')[1];before=target.read_bytes()
        self.store.save(payload)
        self.assertEqual(target.read_bytes(),before)
        self.assertFalse(self.store.history_store.path.exists())

    def test_restore_keeps_old_source_basis_and_detects_staleness(self):
        payload=self.payload('New English');self.store.save(payload)
        version=next(v for v in self.store.history('PROTOCOL.md',payload['unit_id'])['versions'] if v['side']=='before')
        self.source.write_text('# Заголовок\n\nПервый изменён.\n\nВторой текст.\n',encoding='utf-8')
        current=self.store.read('PROTOCOL.md')
        restored=self.store.restore(dict(path='PROTOCOL.md',unit_id=payload['unit_id'],version=version['version'],revision=current['revision'],source_sha256=current['source_sha256']))
        unit=next(u for u in restored['units'] if u['unit_id']==payload['unit_id'])
        self.assertEqual(unit['translation'],'First text.\n');self.assertEqual(unit['status'],'stale')
        self.assertEqual(unit['translated_source'],'Первый текст.\n')
        with self.assertRaises(SourceConflict):self.store.restore(dict(payload,version=version['version']))

    def test_confirmation_of_same_text_after_source_change_is_recorded(self):
        self.source.write_text('# Заголовок\n\nПервый изменён.\n\nВторой текст.\n',encoding='utf-8')
        payload=self.payload('First text.\n');result=self.store.save(payload)
        self.assertEqual(result['pending'],0)
        self.assertEqual(len(self.store.history('PROTOCOL.md',payload['unit_id'])['versions']),2)

    def test_batch_keeps_initial_and_final_translation_in_one_checkpoint(self):
        doc=self.store.read('PROTOCOL.md');unit=next(u for u in doc['units'] if u['source'].startswith('Первый'));ident=unit['unit_id']
        unit['translation']='Intermediate';doc=self.store.save_document(doc,batch_id='run')
        next(u for u in doc['units'] if u['unit_id']==ident)['translation']='Final'
        self.store.save_document(doc,batch_id='run')
        versions=self.store.history('PROTOCOL.md',ident)['versions']
        self.assertEqual({v['value']['translation'] for v in versions},{'First text.\n','Final'})
        with self.store.history_store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)

    def test_failed_batch_write_keeps_last_successful_checkpoint(self):
        from unittest.mock import patch
        doc=self.store.read('PROTOCOL.md');unit=next(u for u in doc['units'] if u['source'].startswith('Первый'));ident=unit['unit_id']
        unit['translation']='Saved chunk';doc=self.store.save_document(doc,batch_id='run')
        next(u for u in doc['units'] if u['unit_id']==ident)['translation']='Failed chunk'
        with patch('protocol_atlas.translations.write_json',side_effect=OSError('disk error')):
            with self.assertRaises(OSError):self.store.save_document(doc,batch_id='run')
        versions=self.store.history('PROTOCOL.md',ident)['versions']
        self.assertEqual({v['value']['translation'] for v in versions},{'First text.\n','Saved chunk'})

    def test_ui_noop_and_restore(self):
        web=self.root/'protocol_atlas/web';web.mkdir(parents=True);(web/'app.js').write_text("const text='Подпись';",encoding='utf-8')
        current=self.store.ui();entry=current['entries'][0]
        current=self.store.save_ui(dict(id=entry['id'],revision=current['revision'],translation='Label'))
        raw=(self.root/'locales/en/ui.json').read_bytes();size=self.store.history_store.path.stat().st_size
        self.store.save_ui(dict(id=entry['id'],revision=current['revision'],translation='Label'))
        self.assertEqual((self.root/'locales/en/ui.json').read_bytes(),raw);self.assertEqual(self.store.history_store.path.stat().st_size,size)
        current=self.store.save_ui(dict(id=entry['id'],revision=current['revision'],translation='Revised'))
        version=next(v for v in self.store.history('@ui',entry['id'])['versions'] if v['value']['translation']=='Label')
        restored=self.store.restore(dict(path='@ui',unit_id=entry['id'],revision=current['revision'],version=version['version']))
        self.assertEqual(restored['entries'][0]['translation'],'Label')

    def test_legacy_migration_is_lossless_and_repeatable(self):
        from protocol_atlas.catalog import digest
        history=self.store.history_store;history.folder.mkdir(parents=True)
        raw=self.store.target('PROTOCOL.md')[1].read_bytes();import json
        value=json.loads(raw);value['path']='PROTOCOL.md';raw=json.dumps(value,ensure_ascii=False).encode()
        old=history.folder/(digest(raw)+'.json');old.write_bytes(raw)
        report=history.migration();self.assertEqual(report['verified_files'],1);self.assertTrue(old.exists())
        name,exported=history.export_legacy(digest(raw));self.assertEqual(name,old.name);self.assertEqual(exported,raw)
        self.assertEqual(history.migration(remove=True)['removed_files'],1)
        self.assertEqual(history.migration(remove=True)['files'],0)

    def test_invalid_archive_prevents_any_deletion(self):
        history=self.store.history_store;history.folder.mkdir(parents=True)
        (history.folder/'broken.json').write_text('not JSON')
        with self.assertRaises(ValueError):history.migration(remove=True)
        self.assertTrue((history.folder/'broken.json').exists())

    def test_only_registered_documents_can_be_written(self):
        for path in ('../outside.md','locales/en/ui.json','.env','docs/absent.md'):
            with self.assertRaises(ValueError):self.store.read(path)
if __name__=='__main__':unittest.main()
