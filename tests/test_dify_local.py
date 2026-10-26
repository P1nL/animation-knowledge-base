import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dify_local, export_knowledge, prepare_pages


class FakeConsole:
    origin = "http://127.0.0.1:18080"

    def __init__(self):
        self.calls = []

    def request(self, method, path, data=None, token=None):
        self.calls.append((method, path, data, token))
        if path == "/console/api/datasets":
            return {"id": "synthetic-dataset"}
        if path == "/console/api/datasets/api-keys":
            return {"token": "synthetic-local-only-key"}
        if path.endswith("/documents?page=1&limit=100"):
            return {"data": []}
        if path.endswith("/document/create-by-text"):
            return {"document": {"id": "synthetic-document"}}
        raise AssertionError(f"Unexpected endpoint in source-import test: {method} {path}")


class DifyLocalTests(unittest.TestCase):
    def test_provider_install_queries_model_category_and_skips_installed_plugins(self):
        class PluginConsole:
            def __init__(self):
                self.calls = []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith('installed-ids?category=model'):
                    return {'plugin_ids': ['langgenius/deepseek']}
                if path.endswith('latest-versions'):
                    return {'versions': {'langgenius/ollama': {'unique_identifier': 'synthetic-signed-identifier'}}}
                if path.endswith('install/marketplace'):
                    return {'task_id': 'synthetic-task'}
                raise AssertionError(path)

        console = PluginConsole()
        dify_local.install_plugins(console, ['langgenius/ollama', 'langgenius/deepseek'])
        self.assertEqual(console.calls[1][2], {'plugin_ids': ['langgenius/ollama']})
        self.assertEqual(console.calls[2][2], {'plugin_unique_identifiers': ['synthetic-signed-identifier']})

    def test_setup_uses_plain_password_but_keeps_generated_account_private(self):
        class SetupConsole:
            calls = []

            def request(self, method, path, data=None):
                self.calls.append((method, path, data))
                if path.endswith('/setup') and method == 'GET':
                    return {'step': 'not_started'}
                return {'result': 'success'}

            def login(self, account):
                self.account = account

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(prepare_pages, 'ROOT', root):
                env = root / 'work/.env'
                env.parent.mkdir()
                env.write_text('INIT_PASSWORD=synthetic-init\n', encoding='utf-8')
                account_path = root / 'work/admin.json'
                console = SetupConsole()
                dify_local.initialize(console, account_path, env)
                account = json.loads(account_path.read_text(encoding='utf-8'))
                setup = next(call[2] for call in console.calls if call[0] == 'POST' and call[1].endswith('/setup'))
                self.assertEqual(setup['password'], account['password'])
                self.assertEqual(console.account, account)

    def test_redirects_cannot_forward_local_credentials_or_source_text(self):
        with self.assertRaisesRegex(ValueError, "stay local"):
            dify_local.NoRedirects().redirect_request(None, None, 307, "redirect", {}, "https://remote.test")

    def test_bootstrap_only_allows_explicit_local_origin(self):
        self.assertEqual(dify_local.local_origin("http://127.0.0.1:18080/"), "http://127.0.0.1:18080")
        self.assertEqual(dify_local.local_origin("http://localhost:18080"), "http://localhost:18080")
        for value in ("https://api.deepseek.com", "http://example.com", "http://localhost.evil.test",
                      "http://user:password@localhost", "http://localhost/path", "http://localhost?target=remote"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                dify_local.Console(value)

    def test_workflow_has_local_retrieval_configurable_chat_and_citations(self):
        payload = dify_local.workflow_payload("synthetic-dataset")
        nodes = {node["id"]: node["data"] for node in payload["graph"]["nodes"]}
        self.assertEqual(nodes["knowledge"]["dataset_ids"], ["synthetic-dataset"])
        self.assertFalse(nodes["knowledge"]["multiple_retrieval_config"]["reranking_enable"])
        self.assertEqual(nodes["llm"]["model"]["name"], "deepseek-flash")
        self.assertFalse(nodes["llm"]["model"]["completion_params"]["thinking"])
        self.assertEqual(nodes["llm"]["context"]["variable_selector"], ["knowledge", "result"])
        self.assertIn("{{#context#}}", nodes["llm"]["prompt_template"][0]["text"])
        self.assertTrue(payload["features"]["retriever_resource"]["enabled"])
        self.assertNotIn("api_key", json.dumps(payload))
        self.assertEqual(len(payload["graph"]["edges"]), 3)
        self.assertNotIn('environment_variables', payload)
        custom = dify_local.workflow_payload("synthetic-dataset", "user/provider", "user-model")
        self.assertEqual(custom["graph"]["nodes"][2]["data"]["model"]["name"], "user-model")
        self.assertNotIn('thinking', custom['graph']['nodes'][2]['data']['model']['completion_params'])

    def test_source_import_retains_draft_label_and_uses_embedding_not_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "corpus/cards.jsonl"
            source.parent.mkdir()
            source.write_text(json.dumps({
                "id": "SYNTHETIC-01", "source_id": "synthetic", "term_ja": "架空",
                "title_zh": "合成测试材料", "context": "not a real book excerpt", "summary_zh": "Synthetic test only",
                "extraction_method": "synthetic", "pdf_pages": [1], "review_status": "needs_human_review",
            }), encoding="utf-8")
            with patch.object(prepare_pages, "ROOT", root), patch.object(export_knowledge, "ROOT", root):
                console = FakeConsole()
                state_path = root / "work/state.json"
                with self.assertRaises(ValueError):
                    dify_local.import_cards(console, state_path, source, False)
                self.assertEqual(console.calls, [])
                state = dify_local.import_cards(console, state_path, source, True)
                request = next(call for call in console.calls if call[1].endswith("/document/create-by-text"))
                body = request[2]
                self.assertEqual(body["doc_form"], "text_model")
                self.assertEqual(body["embedding_model"], "bge-m3")
                self.assertEqual(body['process_rule'], dify_local.CARD_PROCESS_RULE)
                self.assertIn("needs_human_review", body["text"])
                self.assertIn("尚待人工校订", body["text"])
                self.assertEqual(state["dataset_id"], "synthetic-dataset")
                scoped_key = next(call for call in console.calls if call[1].endswith("/api-keys"))
                self.assertEqual(scoped_key[2], {"dataset_ids": ["synthetic-dataset"]})
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)

    def test_resume_records_existing_document_ids_without_reimporting(self):
        class ExistingConsole(FakeConsole):
            def request(self, method, path, data=None, token=None):
                self.calls.append((method, path, data, token))
                if path.endswith('/documents?page=1&limit=100'):
                    return {'data': [{'id': 'existing-document', 'name': 'SYNTHETIC-01.md'}]}
                raise AssertionError('Existing documents must not be recreated or overwritten')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(prepare_pages, 'ROOT', root), patch.object(export_knowledge, 'load_cards', return_value=[{'id': 'SYNTHETIC-01'}]):
                path = root / 'work/state.json'
                dify_local.save_private(path, {'origin': FakeConsole.origin, 'dataset_id': 'synthetic', 'dataset_api_key': 'synthetic-key'})
                console = ExistingConsole()
                state = dify_local.import_cards(console, path, root/'corpus/fixture.jsonl', True)
                self.assertEqual(state['documents'], {'SYNTHETIC-01': 'existing-document'})
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), state)
                self.assertEqual(len(console.calls), 1)

    def test_evaluation_input_is_rejected_before_any_request(self):
        console = FakeConsole()
        with self.assertRaises(ValueError):
            dify_local.import_cards(console, Path("unused"), export_knowledge.ROOT / "evaluation/pilot.json", True)
        self.assertEqual(console.calls, [])

    def test_existing_app_model_settings_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(prepare_pages, "ROOT", root):
                path = root / "work/state.json"
                state = {"origin": FakeConsole.origin, "dataset_id": "synthetic", "app_id": "synthetic-app", "app_configured": True}
                dify_local.save_private(path, state)
                console = FakeConsole()
                self.assertEqual(dify_local.create_app(console, path, "new-provider", "new-model"), state)
                self.assertEqual(console.calls, [])

    def test_private_state_cannot_be_written_into_public_source(self):
        with self.assertRaises(ValueError):
            dify_local.save_private(prepare_pages.ROOT / "public-state.json", {"token": "synthetic"})


if __name__ == "__main__":
    unittest.main()
