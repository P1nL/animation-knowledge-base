"""Offline delivery wiring and routing tests; all external requests are fixtures."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import delivery_nodes as nodes, prepare_delivery as tool, dify_local as d
from scripts import export_knowledge, prepare_pages


class RoutingTests(unittest.TestCase):
    def test_preserve_original_and_do_not_merge_distinct_terms(self):
        q="作监补是否必须处理中一，而不是中1？"
        result=nodes.prepare_query(q,"true")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["original"],q)
        self.assertTrue(result["retrieval_query"].startswith(q))
        self.assertIn("作画監督補佐",result["retrieval_query"])
        self.assertFalse(nodes.prepare_query("这个时间表怎么填？","true")["allowed"])

    def test_not_ready_and_sensitive_query_stop_before_retrieval(self):
        for q,ready in [("作监职责是什么？","false"),("内部项目作监审批记录","true"),
                        ("作监邮箱 person@example.com","true"),("请完全离线解释作监","true")]:
            self.assertFalse(nodes.prepare_query(q,ready)["allowed"])

    def test_web_triggers_and_book_only_precedence(self):
        docs=[{"content":"作监 作監 作画監督 作画监督"}]
        self.assertFalse(nodes.route_web("作监职责",docs,"true","true")["should_search"])
        self.assertTrue(nodes.route_web("现在作监职责",docs,"true","true")["should_search"])
        self.assertTrue(nodes.route_web("作监职责",[],"true","true")["should_search"])
        self.assertFalse(nodes.route_web("只按本书回答现在作监职责",docs,"true","true")["should_search"])
        self.assertFalse(nodes.route_web("本公司谁批准作监返修",[],"true","true")["should_search"])
        self.assertFalse(nodes.route_web("现在作监职责",[],"true","false")["should_search"])

    def test_external_query_is_public_terms_not_raw_context(self):
        q="角色XYZ_PRIVATE_777的作监补职责是什么？"
        result=nodes.route_web(q,[],"true","true")
        payload=json.loads(result["request_body"])
        self.assertNotIn("XYZ_PRIVATE_777",payload["query"])
        self.assertEqual(payload["numResults"],5)
        self.assertEqual(payload["contents"],{"text":{"maxCharacters":3000}})
        self.assertFalse(result["should_search"])
        self.assertEqual(result["reason"],"query_needs_clarification")

    def test_no_search_variants_override_triggers_with_or_without_local_results(self):
        for restriction in ("不用联网", "无需联网", "不需要搜索", "禁止上网", "别搜索",
                            "请只看本书", "仅根据本书", "只参考给定资料", "仅限本书"):
            for docs in ([], [{"content":"作监职责"}]):
                with self.subTest(restriction=restriction, docs=bool(docs)):
                    result=nodes.route_web("最新作监职责是什么？"+restriction,docs,"true","true")
                    self.assertFalse(result["should_search"])
                    self.assertEqual(result["reason"],"book_only")

    def test_official_source_restriction_does_not_mean_book_only(self):
        for q in ("请仅根据官网搜索最新作监职责", "只依据公开来源搜索作监职责"):
            with self.subTest(query=q):
                result=nodes.route_web(q,[],"true","true")
                self.assertTrue(result["should_search"])
                self.assertEqual(result["reason"],"explicit_web")

    def test_search_preserves_feature_versions_negation_and_time(self):
        q="搜索 Blender 4.2 与 4.3 的 Grease Pencil 兼容性区别"
        result=nodes.route_web(q,[],"true","true")
        self.assertTrue(result["should_search"])
        search=json.loads(result["request_body"])["query"]
        self.assertIn("Blender 4.2 与 4.3 Grease Pencil 兼容性 区别",search)
        q="搜索 2024 年原画是否必须使用中一而不是中1"
        result=nodes.route_web(q,[],"true","true")
        self.assertTrue(result["should_search"])
        for token in ("2024", "原画", "是否", "必须", "中一", "而不是", "中1"):
            self.assertIn(token,result["public_query"])

    def test_unknown_constraints_clarify_without_lossy_search(self):
        for q in ("搜索 Blender Geometry Nodes 缓存兼容性", "搜索作监必须有3个人吗", "作监角色XYZ_PRIVATE_777职责"):
            with self.subTest(query=q):
                result=nodes.route_web(q,[],"true","true")
                self.assertFalse(result["should_search"])
                self.assertEqual(result["reason"],"query_needs_clarification")
                self.assertEqual(json.loads(result["request_body"])["query"],"")
                self.assertIn("未执行联网",result["status"])

    def test_web_formats_only_real_text_and_deduplicates(self):
        result={"results":[{"url":"https://example.org/a","title":"A","text":"SOURCE"},
                           {"url":"https://example.org/a","text":"DUPLICATE"},
                           {"url":"http://127.0.0.1/private","text":"PRIVATE"},
                           {"url":"https://example.org/b","summary":"SUMMARY ONLY"}]}
        text=nodes.format_web(json.dumps(result),200)["text"]
        self.assertIn("SOURCE",text)
        self.assertNotIn("DUPLICATE",text)
        self.assertNotIn("PRIVATE",text)
        self.assertNotIn("SUMMARY ONLY",text)
        self.assertIn("未知",text)
        for body,status in [("",0),("bad",200),("{}",401),('{"results":null}',200)]:
            self.assertNotIn('"id": "W1"',nodes.format_web(body,status)["text"])


class FakeConsole:
    origin="http://127.0.0.1:18080"

    def __init__(self):
        self.calls=[]; self.graphs={}; self.documents={}; self.dataset={}

    def request(self,method,path,data=None,token=None):
        self.calls.append((method,path,deepcopy(data)))
        if path=="/console/api/apps": return {"id":"separate-delivery-app"}
        if path.endswith("/workflows/draft"):
            if method=="POST": self.graphs[path]=deepcopy(data)
            return deepcopy(self.graphs.get(path,{}))
        if path.endswith("/models/credentials"): return {}
        if path=="/console/api/datasets":
            self.dataset={"id":"separate-delivery-dataset"}
            return self.dataset
        if path=="/console/api/datasets/separate-delivery-dataset":
            if method=="PATCH": self.dataset.update(deepcopy(data))
            return self.dataset
        if path=="/console/api/datasets/api-keys": return {"token":"SYNTHETIC_DATASET_KEY"}
        if path.endswith("/documents?page=1&limit=100"): return {"data":list(self.documents.values())}
        if path.endswith("/document/create-by-text"):
            row={"id":data["name"],"name":data["name"],"indexing_status":"completed"}
            self.documents[data["name"]]=row
            return {"document":row}
        if path=="/v1/datasets/separate-delivery-dataset": return self.dataset
        raise AssertionError((method,path))


class DeliveryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        for module in (tool,d,prepare_pages,export_knowledge):
            self.stack.enter_context(patch.object(module,"ROOT",self.root))
        release=self.root/"corpus/releases/source-v3"; release.mkdir(parents=True)
        cards=[{"id":f"book-{i:03}","source_id":"synthetic","term_ja":"TERM","title_zh":"TITLE",
                "context":"CONTEXT","summary_zh":"SOURCE_ONLY_SENTINEL","pdf_pages":[1],
                "review_status":"needs_human_review","extraction_method":"synthetic"} for i in range(1,35)]
        (release/"cards.jsonl").write_text("".join(json.dumps(c)+"\n" for c in cards),encoding="utf-8")
        (release/"scope.json").write_text(json.dumps({"version":"source-v3","card_count":34,"approved_pdf_pages":[1]}),encoding="utf-8")
        (self.root/"deploy").mkdir()
        self.blank="DASHSCOPE_API_KEY=\nEXA_API_KEY=\nEMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1\nEMBEDDING_MODEL=text-embedding-v4\nEMBEDDING_DIMENSIONS=1024\nWEB_ENABLED=true\n"
        (self.root/"deploy/delivery.env.example").write_text(self.blank,encoding="utf-8")
        self.bundle=self.root/"work/delivery-v1"

    def test_offline_prepare_blank_keys_source_only_and_no_overwrite(self):
        with patch.object(tool,"connect",side_effect=AssertionError("No network")):
            tool.prepare(self.bundle)
            settings=tool.validate_bundle(self.bundle)
        self.assertEqual(settings["DASHSCOPE_API_KEY"],"")
        self.assertEqual(settings["EXA_API_KEY"],"")
        self.assertEqual(len(list((self.bundle/"sources").glob("*.md"))),34)
        self.assertIn("needs_human_review",(self.bundle/"sources/book-001.md").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError,"already exists"): tool.prepare(self.bundle)
        (self.bundle/"sources/gold.md").write_text("REFERENCE",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"snapshot"): tool.validate_bundle(self.bundle)

    def test_workflow_original_query_hybrid_and_secret_only_in_http_auth(self):
        p=tool.workflow("new-dataset",False,"",True)
        n={n["id"]:n["data"] for n in p["graph"]["nodes"]}
        self.assertEqual(n["knowledge"]["dataset_ids"],["new-dataset"])
        self.assertEqual(n["knowledge"]["multiple_retrieval_config"]["weights"],tool.WEIGHTS)
        self.assertEqual(n["llm"]["prompt_template"][1]["text"],"{{#query.original#}}")
        self.assertEqual(sum(x["type"]=="llm" for x in n.values()),1)
        self.assertEqual(sum(x["type"]=="http-request" for x in n.values()),1)
        self.assertEqual(n["exa"]["retry_config"]["max_retries"],0)
        self.assertEqual(n["exa"]["error_strategy"],"default-value")
        self.assertEqual(n["exa"]["authorization"]["config"]["api_key"],"{{#env.EXA_API_KEY#}}")
        for item in n.values():
            if item["type"]=="code":
                self.assertNotIn(["env","EXA_API_KEY"],[v["value_selector"] for v in item["variables"]])
        env={v["name"]:v for v in p["environment_variable_patch"]["environment_variables"]}
        self.assertEqual(env["EXA_API_KEY"]["value"],"")
        self.assertEqual(env["DELIVERY_READY"]["value"],"false")
        self.assertEqual(env["WEB_ENABLED"]["value"],"true")

    def test_activation_requires_authorization_and_keys_before_network(self):
        tool.prepare(self.bundle)
        with patch.object(tool,"connect",side_effect=AssertionError("No network")):
            with self.assertRaisesRegex(ValueError,"authorization"): tool.activate(self.bundle)
            with self.assertRaisesRegex(ValueError,"Fill"): tool.activate(self.bundle,True)

    def test_credential_refresh_requires_authorization_and_key_before_network(self):
        tool.prepare(self.bundle)
        with patch.object(tool,"connect",side_effect=AssertionError("No network")):
            with self.assertRaisesRegex(ValueError,"authorization"): tool.refresh_embedding_credentials(self.bundle)
            with self.assertRaisesRegex(ValueError,"Fill"): tool.refresh_embedding_credentials(self.bundle,True)

    def test_explicit_key_refresh_after_interruption_does_not_retry_documents(self):
        tool.prepare(self.bundle); c=FakeConsole()
        with redirect_stdout(io.StringIO()): tool.install_draft(self.bundle,c)
        settings=self.blank.replace("DASHSCOPE_API_KEY=","DASHSCOPE_API_KEY=SYNTHETIC_OLD").replace("EXA_API_KEY=","EXA_API_KEY=SYNTHETIC_EXA")
        (self.bundle/"secrets.env").write_text(settings,encoding="utf-8")
        original=c.request
        def interrupted(method,path,data=None,token=None):
            if path.endswith("/document/create-by-text"): raise RuntimeError("synthetic interruption")
            return original(method,path,data,token)
        with patch.object(c,"request",side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError,"interruption"): tool.activate(self.bundle,True,c)
        before=d.read_json(self.bundle/"state.json")
        self.assertTrue(before["embedding_configured"])
        (self.bundle/"secrets.env").write_text(settings.replace("SYNTHETIC_OLD","SYNTHETIC_NEW"),encoding="utf-8")
        count=len(c.calls)
        with redirect_stdout(io.StringIO()): tool.refresh_embedding_credentials(self.bundle,True,c)
        calls=c.calls[count:]
        self.assertEqual(len(calls),1)
        self.assertTrue(calls[0][1].endswith("/models/credentials"))
        self.assertEqual(calls[0][2]["credentials"]["api_key"],"SYNTHETIC_NEW")
        self.assertEqual(d.read_json(self.bundle/"state.json"),before)
        with self.assertRaisesRegex(ValueError,"incomplete document submission"): tool.activate(self.bundle,True,c)

    def test_failed_credential_refresh_does_not_change_readiness_or_state(self):
        tool.prepare(self.bundle); c=FakeConsole()
        with redirect_stdout(io.StringIO()): tool.install_draft(self.bundle,c)
        before=d.read_json(self.bundle/"state.json")
        (self.bundle/"secrets.env").write_text(self.blank.replace("DASHSCOPE_API_KEY=","DASHSCOPE_API_KEY=SYNTHETIC_NEW"),encoding="utf-8")
        with patch.object(c,"request",side_effect=RuntimeError("synthetic credential failure")):
            with self.assertRaisesRegex(RuntimeError,"credential failure"): tool.refresh_embedding_credentials(self.bundle,True,c)
        self.assertEqual(d.read_json(self.bundle/"state.json"),before)

    def test_install_only_creates_own_gated_draft(self):
        tool.prepare(self.bundle); c=FakeConsole()
        with redirect_stdout(io.StringIO()): tool.install_draft(self.bundle,c)
        self.assertFalse(d.read_json(self.bundle/"state.json")["ready"])
        self.assertTrue(all("/datasets" not in p and "/run" not in p and "/publish" not in p and "/credentials" not in p for _,p,_ in c.calls))

    def test_authorized_activation_indexes_sources_once_without_chat_or_search(self):
        tool.prepare(self.bundle); c=FakeConsole()
        with redirect_stdout(io.StringIO()): tool.install_draft(self.bundle,c)
        settings=self.blank.replace("DASHSCOPE_API_KEY=","DASHSCOPE_API_KEY=SYNTHETIC_ALI").replace("EXA_API_KEY=","EXA_API_KEY=SYNTHETIC_EXA")
        (self.bundle/"secrets.env").write_text(settings,encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            tool.activate(self.bundle,True,c)
            tool.activate(self.bundle,True,c)
        uploads=[data for _,p,data in c.calls if p.endswith("/document/create-by-text")]
        self.assertEqual(len(uploads),34)
        self.assertTrue(all("SOURCE_ONLY_SENTINEL" in u["text"] for u in uploads))
        self.assertTrue(all(u["retrieval_model"]["search_method"]=="hybrid_search" for u in uploads))
        self.assertEqual(sum(p.endswith("/models/credentials") for _,p,_ in c.calls),1)
        self.assertTrue(d.read_json(self.bundle/"state.json")["ready"])
        self.assertTrue(all("/run" not in p and "/publish" not in p and "api.exa.ai" not in p for _,p,_ in c.calls))

    def test_api_endpoint_and_model_identity_are_explicit(self):
        tool.prepare(self.bundle); settings=tool.validate_bundle(self.bundle)
        credentials=tool.provider_credentials(settings)
        self.assertEqual(credentials["max_chunks"],"10")
        self.assertEqual(credentials["context_size"],"8192")
        for change in ({"EMBEDDING_BASE_URL":"https://other.example/compatible-mode/v1"},
                       {"EMBEDDING_MODEL":"Qwen/Qwen3-Embedding-4B"}):
            with self.assertRaises(ValueError): tool.provider_credentials({**settings,**change})


if __name__=="__main__":
    unittest.main()
