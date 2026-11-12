"""Check workflow wiring; readiness/replacement behavior is tested offline separately."""
from pathlib import Path
import unittest


class ReplacementWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()

    def test_replacement_is_explicit_and_manual(self):
        self.assertIn('default: false', self.workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.replace_existing", self.workflow)
        self.assertIn('scripts/production_readiness.py --date "$RADIO_DATE" --replace-existing', self.workflow)
        self.assertIn('scripts/publish_work.py --date "$RADIO_DATE" --replace-existing', self.workflow)

    def test_refresh_precedes_dependency_setup(self):
        self.assertLess(self.workflow.index('git checkout -B main origin/main'),
                        self.workflow.index('actions/setup-python'))
        self.assertLess(self.workflow.index('git checkout -B main origin/main'),
                        self.workflow.index('pip install'))

    def test_one_date_and_readiness_gate(self):
        self.assertEqual(self.workflow.count('--resolve-date'), 1)
        self.assertIn('inputs.broadcast_date', self.workflow)
        self.assertNotIn('date +%F', self.workflow)
        self.assertEqual(self.workflow.count('RADIO_DATE: ${{ steps.day.outputs.today }}'), 3)
        self.assertLess(self.workflow.index('Diagnose production readiness'), self.workflow.index('Generate episode'))
        for name in ('Restore MASURADIO stage cache', 'Generate episode', 'Commit episode'):
            step = self.workflow.split('      - name: ' + name, 1)[1].split('      - name:', 1)[0]
            self.assertIn("if: steps.existing.outputs.ready != 'true'", step)

    def test_only_stage_caches_are_best_effort(self):
        steps = self.workflow.split('      - name:')[1:]
        tolerant = [step.splitlines()[0].strip() for step in steps if 'continue-on-error: true' in step]
        self.assertEqual(tolerant, ['Restore MASURADIO stage cache', 'Save MASURADIO stage cache'])
        self.assertIn("if: always() && steps.existing.outputs.ready == 'false'", self.workflow)
        self.assertNotIn('|| true', self.workflow)
