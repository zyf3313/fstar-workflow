import unittest
from pathlib import Path

from fstar.content import extract_artifact, load_mapping
from fstar.extensions import grants, includes
from fstar.runtime.hooks import PROMPT_STATE_TAG

ROOT = Path(__file__).resolve().parents[1] / 'resources'


class PlanningContractTests(unittest.TestCase):
    def test_task_and_design_templates_remain_extractable(self):
        for relative in ('task/plan', 'scenarios/software/design'):
            text = (ROOT / 'templates' / (relative + '.md')).read_text(encoding='utf-8')
            mapping = load_mapping(ROOT / 'templates' / (relative + '.mapping.yaml'))
            parsed = extract_artifact(text, mapping, artifact=relative + '.md')
            self.assertTrue(parsed.ok, parsed.diagnostics)
            self.assertTrue(parsed.items)
            self.assertEqual(len({item.id for item in parsed.items}), len(parsed.items))

    def test_planning_breadcrumb_keeps_scope_and_grants(self):
        text = (ROOT / 'runtime' / 'prompt-states.md').read_text(encoding='utf-8')
        states = {match.group('tag'): match.group('body') for match in PROMPT_STATE_TAG.finditer(text)}
        self.assertEqual(set(states), {'no_task', 'planning', 'in_progress', 'awaiting_acceptance'})
        planning = states['planning']
        for phrase in ('persistent development', 'plan.md', 'criteria', 'specifications',
                       'design', 'grants', 'session-only'):
            self.assertIn(phrase, planning)
        self.assertNotIn('simple items proceed', planning)
        # An unrelated grant must not imply plan or design authorization.
        context = grants([{'id': 'planning-review', 'scope': 'custom',
                           'included': ['prd'], 'excluded': ['plan', 'design'],
                           'source': {'type': 'test'}}])
        self.assertFalse(includes(context, 'planning-review', 'plan'))
        self.assertFalse(includes(context, 'planning-review', 'design'))


if __name__ == '__main__':
    unittest.main()
