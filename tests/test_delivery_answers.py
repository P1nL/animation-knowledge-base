"""Offline regressions for final answer display; no model/search requests."""
import json
import unittest

from scripts import delivery_nodes as nodes, prepare_delivery as delivery


class PublicEvidenceTests(unittest.TestCase):
    def test_removes_only_management_preamble_and_preserves_citations(self):
        header = '# Layout作监\r\n- 条目 ID：book-018\r\n- PDF 页码：63\r\n'
        body = '\r\n## 必要日文原句\r\n普段は作画監督が兼務する。\r\n## 语境和边界\r\n具体项目仍以项目资料为准。\r\n'
        content = header + '- 整理方法：ai_assisted_ocr_source_review\r\n- 校订状态：needs_human_review\r\n**内部草案：尚待人工校订，不是已确认的知识或评测真值。**\r\n' + body
        document = {'content':content,'title':'book-018.md','metadata':{'document_id':'source-id','position':1},'score':0.7}
        result = nodes.public_evidence([document])['result'][0]
        self.assertEqual(result['content'],header+body)
        self.assertEqual({k:v for k,v in result.items() if k!='content'},
                         {k:v for k,v in document.items() if k!='content'})
        self.assertEqual(document['content'],content)

    def test_actual_body_text_about_review_is_not_removed(self):
        content = '# 来源资料\n## 语境和边界\n- 校订状态：这里是在说明真实业务字段。\n内部草案：尚待人工校订，不是已确认的知识或评测真值。\n'
        self.assertEqual(nodes.public_evidence([{'content':content}])['result'][0]['content'],content)
        self.assertEqual(nodes.public_evidence([]),{'result':[]})

    def test_model_context_is_cleaned_without_new_retrieval_or_model_calls(self):
        workflow = delivery.workflow('synthetic-dataset',True,'',True)
        by_id = {n['id']:n['data'] for n in workflow['graph']['nodes']}
        edges = {(e['source'],e['target']) for e in workflow['graph']['edges']}
        self.assertEqual(by_id['llm']['context']['variable_selector'],['public_evidence','result'])
        self.assertIn(('knowledge','public_evidence'),edges)
        self.assertIn(('public_evidence','route'),edges)
        self.assertNotIn(('knowledge','route'),edges)
        self.assertEqual(by_id['public_evidence']['outputs'],{'result':{'type':'array[object]'}})
        self.assertEqual(sum(n['type']=='knowledge-retrieval' for n in by_id.values()),1)
        namespace = {}
        exec(by_id['public_evidence']['code'],namespace)
        result = namespace['main']([{'content':'- 校订状态：needs_human_review\n## 正文\n保留正文。'}])
        self.assertEqual(result['result'][0]['content'],'## 正文\n保留正文。')


class AnswerFinalizationTests(unittest.TestCase):
    def evidence(self):
        return nodes.format_web(json.dumps({'results':[
            {'url':'https://example.org/one','text':'First source'},
            {'url':'https://example.org/two','text':'Second source'},
            {'url':'https://example.org/three','text':'Third source'},
        ]}),200)['text']

    def test_missing_urls_are_added_for_cited_sources_only(self):
        text=nodes.finalize_answer('版本存在变化[W1][W3]。',self.evidence())['text']
        self.assertIn('- [W1] <https://example.org/one>',text)
        self.assertIn('- [W3] <https://example.org/three>',text)
        self.assertNotIn('https://example.org/two',text)
        self.assertTrue(text.startswith('版本存在变化[W1][W3]。'))

    def test_repeated_and_grouped_citations_have_one_mapping(self):
        text=nodes.finalize_answer('变化[W1、W3]，另见[W1]。',self.evidence())['text']
        self.assertEqual(text.count('https://example.org/one'),1)
        self.assertEqual(text.count('https://example.org/three'),1)
        self.assertEqual(nodes.finalize_answer(text,self.evidence())['text'],text)

    def test_unknown_reference_is_not_assigned_a_guessed_url(self):
        text=nodes.finalize_answer('依据[W9]。',self.evidence())['text']
        self.assertIn('W9未对应本轮返回的有效网页来源',text)
        self.assertNotIn('https://',text)
        self.assertEqual(nodes.finalize_answer('资料未提及。','未联网。')['text'],'资料未提及。')

    def test_invalid_or_empty_evidence_cannot_create_a_source_link(self):
        for url,excerpt in [('javascript:alert(1)','text'),('http://127.0.0.1/private','text'),
                            ('https://example.org/one',''),('https://example.org/a\nspoof','text')]:
            evidence='Sources\n'+json.dumps([{'id':'W1','url':url,'text_excerpt':excerpt}])
            text=nodes.finalize_answer('依据[W1]。',evidence)['text']
            self.assertNotIn('### 来源链接',text)
            self.assertIn('无法核验',text)

    def test_absence_only_categorical_lead_is_qualified(self):
        original='**结论：不是。** 现有本地资料没有任何“作监必须使用某软件”的规定；联网证据也不支持这一说法。\n\n具体项目仍需查看规定。'
        text=nodes.finalize_answer(original,'未联网。')['text']
        self.assertTrue(text.startswith('**结论：现有资料不足以支持这一说法。**'))
        self.assertNotIn('**结论：不是。**',text)
        self.assertIn('具体项目仍需查看规定。',text)

    def test_explicit_counterevidence_negative_is_not_rewritten(self):
        for original in ('**结论：不是。** 本书明确说明两者用途不同。',
                         '不是。第50页明确规定该流程不适用这一情形。',
                         '没有证据表明必须使用该软件。'):
            self.assertEqual(nodes.finalize_answer(original,'未联网。')['text'],original)

    def test_qualified_answers_and_actual_missing_data_are_preserved(self):
        for original in ('现有资料不足以支持这一说法。具体项目需进一步核实。',
                         '无法据此判断。', '没有。表内对应位置确实为空。'):
            self.assertEqual(nodes.finalize_answer(original,'未联网。')['text'],original)

    def test_workflow_uses_finalized_text_without_an_extra_model(self):
        workflow=delivery.workflow('synthetic-dataset',True,'',True)
        by_id={n['id']:n['data'] for n in workflow['graph']['nodes']}
        edges={(e['source'],e['target']) for e in workflow['graph']['edges']}
        self.assertIn(('llm','finalize'),edges)
        self.assertIn(('finalize','answer'),edges)
        self.assertNotIn(('llm','answer'),edges)
        self.assertEqual(by_id['answer']['answer'],'{{#finalize.text#}}')
        self.assertEqual(by_id['blocked']['answer'],'{{#query.message#}}')
        self.assertEqual(sum(n['type']=='llm' for n in by_id.values()),1)
        self.assertEqual(sum(n['type']=='http-request' for n in by_id.values()),1)
        self.assertIn('缺少支持证据不等于已有反证',delivery.SYSTEM)
        namespace={}
        exec(by_id['finalize']['code'],namespace)
        result=namespace['main']('版本变化[W1]。',self.evidence())
        self.assertIn('https://example.org/one',result['text'])

    def test_prompt_uses_plain_language_with_parenthetical_terms(self):
        prompt=delivery.SYSTEM
        self.assertIn('优先用自然、易懂的中文说明含义',prompt)
        self.assertIn('将对应专业术语放在括号内',prompt)
        self.assertIn('不擅自合并不同概念',prompt)
        self.assertIn('原文引用或用户明确要求的原样内容不改写',prompt)
        self.assertIn('{{#context#}}',prompt)
        self.assertIn('{{#web_join.output#}}',prompt)
        for case_rule in ('私人审批状态','公开示例模板当作实际镜头','是否必须、是否一律、是否禁止'):
            self.assertNotIn(case_rule,prompt)


if __name__=='__main__':
    unittest.main()
