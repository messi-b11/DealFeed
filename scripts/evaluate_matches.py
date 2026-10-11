"""Small fixed internal demo evaluation; no inference and no production accuracy claim.
Run: .venv/bin/python -m scripts.evaluate_matches
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from backend.matching import generate_matches
from backend.store import Store

# The category-only baseline ignores all buyer constraints and sorts business IDs.
INTENTS = [
    {'name': 'Warm editorial restaurant', 'changes': {'desiredStandard': 'warm editorial'}, 'first': 'studio-north', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
    {'name': 'Bold premium hospitality', 'changes': {'desiredStandard': 'bold luxury visual'}, 'first': 'daybreak-design', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
    {'name': 'Accessible calm community cafe', 'changes': {'desiredStandard': 'accessible calm minimal'}, 'first': 'common-ground-web', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
    {'name': 'Playful bilingual cafe', 'changes': {'desiredStandard': 'playful colorful', 'mustHaves': ['Reservation integration', 'Bilingual content']}, 'first': 'good-people', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
    {'name': 'Budget ceiling $2,400', 'changes': {'budgetCents': 240000}, 'first': 'common-ground-web', 'allowed': ['common-ground-web']},
    {'name': 'Budget ceiling $3,000', 'changes': {'budgetCents': 300000}, 'first': 'juniper-digital', 'allowed': ['juniper-digital', 'common-ground-web', 'good-people']},
    {'name': 'Budget ceiling below every sample minimum', 'changes': {'budgetCents': 100000}, 'first': None, 'allowed': []},
    {'name': 'On-site work required', 'changes': {'deliveryMode': 'onsite'}, 'first': None, 'allowed': []},
    {'name': 'Unknown budget remains open', 'changes': {'budgetCents': None}, 'first': 'studio-north', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
    {'name': 'Repeated marketing words cannot rescue reservation conflict', 'changes': {'keywords': ['editorial'] * 30}, 'first': 'studio-north', 'allowed': ['studio-north', 'juniper-digital', 'common-ground-web', 'daybreak-design', 'good-people']},
]


def main():
    os.environ['AI_MODE'] = 'rehearsal'
    reports = []
    with TemporaryDirectory() as tmp:
        store = Store(tmp + '/evaluation.sqlite')
        baseline = sorted({p['businessId'] for p in store.list('project') if not p.get('archived') and p['category'] == 'Website development'})[:5]
        for intent in INTENTS:
            criteria = {'inspirationProjectIds': ['poppy-web'], 'description': 'A responsive restaurant website with menus and reservations.', 'serviceCategory': 'Website development',
                        'budgetCents': 500000, 'currency': 'USD', 'deliverables': [{'id': 'site', 'label': 'Responsive website', 'mandatory': True}, {'id': 'booking', 'label': 'Reservation integration', 'mandatory': True}],
                        'mustHaves': ['Reservation integration'], 'desiredStandard': 'warm editorial', 'deliveryMode': 'remote', 'keywords': [], **intent['changes']}
            matches = generate_matches(store, criteria)['matches']
            actual = [m['businessId'] for m in matches]
            allowed = set(intent['allowed'])
            reports.append({'intent': intent['name'], 'results': actual, 'expectedTopOne': intent['first'], 'topOneCorrect': (actual[0] if actual else None) == intent['first'],
                            'qualifiedTopFive': sum(id_ in allowed for id_ in actual), 'baselineQualifiedTopFive': sum(id_ in allowed for id_ in baseline),
                            'hardConstraintViolations': len(set(actual) - allowed),
                            'unsupportedEvidenceReferences': sum(e['businessId'] != m['businessId'] for m in matches for e in m['evidence'])})
    report = {'mode': 'deterministic_rehearsal', 'sampleSize': len(reports), 'notice': 'Internal fixed fictional-fixture evaluation. Not live AI validation or market accuracy. Unknown capabilities may qualify with unresolved labels.',
              'topOneCorrect': sum(r['topOneCorrect'] for r in reports), 'qualifiedTopFive': sum(r['qualifiedTopFive'] for r in reports),
              'baselineQualifiedTopFive': sum(r['baselineQualifiedTopFive'] for r in reports), 'hardConstraintViolations': sum(r['hardConstraintViolations'] for r in reports),
              'unsupportedEvidenceReferences': sum(r['unsupportedEvidenceReferences'] for r in reports), 'results': reports}
    Path('docs/MATCH_EVALUATION.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}))
    return 0 if report['hardConstraintViolations'] == 0 and report['unsupportedEvidenceReferences'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
