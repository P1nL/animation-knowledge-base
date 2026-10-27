"""Human confirmation changes status/display, never historical evidence or results."""
import json
from pathlib import Path
import unittest

from scripts import export_knowledge as export, prepare_delivery as delivery

ROOT = Path(__file__).resolve().parents[1]


class HumanReviewTests(unittest.TestCase):
    def test_source_successor_preserves_content_and_confirms_all_cards(self):
        old=export.load_cards(ROOT/'corpus/releases/source-v3/cards.jsonl',include_drafts=True)
        new=export.load_cards(ROOT/'corpus/releases/source-v4/cards.jsonl')
        self.assertEqual(len(new),34)
        self.assertEqual(sum(c['review_status']=='needs_human_review' for c in old),22)
        fields=('id','source_id','term_ja','title_zh','context','summary_zh','original_excerpt_ja',
                'pdf_pages','printed_pages','ambiguities','related_terms','extraction_method')
        for a,b in zip(old,new):
            self.assertEqual({k:a.get(k) for k in fields},{k:b.get(k) for k in fields})
            self.assertEqual(b['review_status'],'human_reviewed')
            self.assertEqual(b['review']['reviewer'],'user')

    def test_current_export_omits_review_and_author_labels(self):
        for card in export.load_cards(ROOT/'corpus/releases/source-v4/cards.jsonl'):
            text=export.render_card(card)
            for label in ('已人工审核','AI整理','AI辅助','ai_','校订状态','整理方法','human_reviewed','needs_human_review'):
                self.assertNotIn(label,text)
            self.assertIn(card['summary_zh'],text)
            self.assertIn('PDF 页码',text)

    def test_reference_successor_only_changes_question_review_status(self):
        old=json.loads((ROOT/'evaluation/revisions/final_v1_2_review.json').read_text(encoding='utf-8'))
        new=json.loads((ROOT/'evaluation/revisions/final_v1_3_human_reviewed.json').read_text(encoding='utf-8'))
        self.assertEqual(len(new['questions']),30)
        for a,b in zip(old['questions'],new['questions']):
            self.assertEqual({k:v for k,v in a.items() if k!='gold_status'},
                             {k:v for k,v in b.items() if k!='gold_status'})
            self.assertEqual(b['gold_status'],'human_reviewed')
        self.assertFalse(new['held_out_eligible'])
        self.assertFalse(new['chat_calls_authorized'])
        self.assertIsNone(new['scoring']['results'])
        with self.assertRaisesRegex(ValueError,'Only corpus'):
            export.load_cards(ROOT/'evaluation/revisions/final_v1_3_human_reviewed.json')

    def test_delivery_copy_has_no_author_or_review_badges(self):
        workflow=delivery.workflow('synthetic-dataset',True,'',False)
        opening=workflow['features']['opening_statement']
        self.assertIn('依据书内资料回答',opening)
        for label in ('人工','AI','审核','待审'):
            self.assertNotIn(label,opening)
        llm=next(n['data'] for n in workflow['graph']['nodes'] if n['id']=='llm')
        prompt=llm['prompt_template'][0]['text']
        self.assertIn('不附加整理者身份、生成方式、审核类别或状态标识',prompt)
        self.assertIn('用户明确询问来源或处理过程时按事实说明',prompt)
        self.assertNotIn('FINAL-01',prompt)


if __name__=='__main__':
    unittest.main()
