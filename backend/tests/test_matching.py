from copy import deepcopy
import pytest
from backend.agent import InferenceUnavailable
from backend.store import Store
from backend.matching import (generate_matches, compare_deal, validate_selection, validate_insights,
                              evidence_fingerprint, completed)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_MODE', 'rehearsal')
    return Store(str(tmp_path / 'matching.sqlite'))


def criteria(**changes):
    return {'inspirationProjectIds': ['poppy-web'], 'description': 'A responsive restaurant website with seasonal menus and reservations.',
            'serviceCategory': 'Website development', 'budgetCents': 500000, 'currency': 'USD',
            'deliverables': [{'id': 'site', 'label': 'Responsive website', 'mandatory': True}, {'id': 'booking', 'label': 'Reservation integration', 'mandatory': True}],
            'keywords': ['restaurant'], 'mustHaves': ['Reservation integration'], 'desiredStandard': 'warm editorial',
            'deliveryMode': 'remote', 'location': 'Kansas City', **changes}


def test_five_distinct_evidence_backed_providers_and_near_miss(store):
    result = generate_matches(store, criteria())
    assert len(result['matches']) == 5
    assert len({m['businessId'] for m in result['matches']}) == 5
    assert 'morrow-studio' not in {m['businessId'] for m in result['matches']}
    assert result['mode'] == 'rehearsal' and result['shortfallReason'] is None
    for match in result['matches']:
        for id_ in match['comparableProjectIds']:
            project = store.get('project', id_)
            assert project['businessId'] == match['businessId'] and completed(project)
        assert all(e['businessId'] == match['businessId'] for e in match['evidence'])
        assert 'score' not in match and 'percentage' not in match


def test_meaningful_style_budget_delivery_preferences_change_results(store):
    warm = generate_matches(store, criteria())
    visual = generate_matches(store, criteria(desiredStandard='bold luxury visual'))
    assert warm['matches'][0]['businessId'] == 'studio-north'
    assert visual['matches'][0]['businessId'] == 'daybreak-design'
    cheap = generate_matches(store, criteria(budgetCents=240000))
    assert [m['businessId'] for m in cheap['matches']] == ['common-ground-web']
    assert cheap['shortfallReason']
    assert generate_matches(store, criteria(deliveryMode='onsite'))['matches'] == []


def test_unknown_budget_and_requirement_stay_unresolved(store):
    result = generate_matches(store, criteria(budgetCents=None, mustHaves=['Native desktop POS synchronization']))
    assert len(result['matches']) == 5
    for match in result['matches']:
        assert match['budget']['status'] == 'unknown'
        unknown = next(c for c in match['criteria'] if c['id'] == 'must:0')
        assert unknown['status'] == 'unknown' and not unknown['evidenceIds']


def test_keyword_repetition_never_overrides_mandatory_conflict(store):
    one = generate_matches(store, criteria(keywords=['editorial']))
    many = generate_matches(store, criteria(keywords=['editorial'] * 50))
    assert [m['businessId'] for m in one['matches']] == [m['businessId'] for m in many['matches']]
    assert 'morrow-studio' not in [m['businessId'] for m in many['matches']]


@pytest.mark.parametrize('change', [{'archived': True}, {'status': 'in_progress'}, {'visibility': 'private'}, {'completed': False}, {'publicShareable': False}])
def test_archived_incomplete_private_project_cannot_support_recommendation(store, change):
    project = store.get('project', 'ember-dining')
    store.put('project', {**project, **change})
    result = generate_matches(store, criteria())
    assert len(result['matches']) == 4
    assert 'daybreak-design' not in {m['businessId'] for m in result['matches']}


def test_missing_completion_metadata_not_treated_as_completed():
    assert not completed({'id': 'missing'})


def test_wrong_service_and_archived_inspiration_rejected(store):
    other = generate_matches(store, criteria(serviceCategory='Catering', inspirationProjectIds=['harvest-dinner'], mustHaves=[], deliverables=[]))
    assert {m['businessId'] for m in other['matches']} == {'gather-table'}
    with pytest.raises(ValueError):
        generate_matches(store, criteria(inspirationProjectIds=['olive-table']))


def test_evidence_mismatch_and_unknown_ids_rejected(store):
    result = generate_matches(store, criteria())
    candidates = result['matches']
    selection = {'rankedBusinessIds': [m['businessId'] for m in candidates]}
    validate_selection(selection, candidates)
    tampered = deepcopy(candidates)
    tampered[0]['evidence'][0]['businessId'] = 'fake-business'
    with pytest.raises(ValueError):
        validate_selection(selection, tampered)
    with pytest.raises(ValueError):
        validate_selection({'rankedBusinessIds': ['nonexistent']}, candidates)


def test_semantic_inference_requires_owned_exact_quote(store):
    match = generate_matches(store, criteria())['matches'][0]
    source = match['evidence'][0]
    insight = {'businessIds': [match['businessId']], 'detail': 'The portfolio suggests an editorial approach that may fit this customer.',
               'quotes': [{'evidenceId': source['id'], 'quote': source['excerpt'][:40]}]}
    assert validate_insights([insight], match['evidence'], [match['businessId']])[0]['label'] == 'AI inference'
    insight['quotes'][0]['quote'] = 'This fabricated result never happened.'
    with pytest.raises(ValueError):
        validate_insights([insight], match['evidence'], [match['businessId']])


def test_fixture_dates_and_version_invalidation(store):
    result = generate_matches(store, criteria())
    website = next(e for e in result['matches'][0]['evidence'] if e['kind'] == 'website')
    assert website['provenance'] == 'sample' and website['retrievedAt'] is None
    assert website['fixtureCreatedAt'] and '.example/' in website['url']
    ids = [m['businessId'] for m in result['matches']]
    before = evidence_fingerprint(store, ids)
    assert before == evidence_fingerprint(store, list(reversed(ids)))
    project = store.get('project', 'poppy-web')
    store.put('project', {**project, 'evidenceVersion': 3})
    assert evidence_fingerprint(store, ids) != before


def proposals():
    return [{'id': 'p1', 'requestId': 'r1', 'dealId': 'd1', 'businessId': 'juniper-digital', 'price': 4000.01,
             'timeline': 'Four weeks after content delivery', 'scope': 'Responsive website with seasonal menus.',
             'fitStatement': 'Warm restaurant design matches our completed portfolio.', 'approach': 'Warm visual design with an editable menu.',
             'coverage': [{'deliverableId': 'site', 'status': 'included', 'detail': 'Responsive website included'}, {'deliverableId': 'booking', 'status': 'included', 'detail': 'Integrate an existing reservation service'}]},
            {'id': 'p2', 'requestId': 'r2', 'dealId': 'd1', 'businessId': 'studio-north', 'price': 3500.10,
             'timeline': 'Five weeks', 'scope': 'An editorial website design with seasonal menus.',
             'coverage': [{'deliverableId': 'site', 'status': 'included', 'detail': 'Responsive website included'}]}]


def test_scope_omission_is_unknown_and_money_calculated_exactly(store):
    ps = proposals()
    deal = {'id': 'd1', 'criteria': criteria(), 'businessIds': [p['businessId'] for p in ps]}
    comparison = compare_deal(store, deal, ps)
    first, second = comparison['offers']
    assert first['priceCents'] == 400001
    assert first['cheapestDifferenceCents'] == 49991
    assert first['budgetDifferenceCents'] == -99999
    assert next(c for c in second['coverage'] if c['deliverableId'] == 'booking')['status'] == 'not_stated'
    finding = next(f for f in comparison['findings'] if f['id'] == 'difference:booking')
    assert set(finding['evidenceIds']) == {'proposal:p1', 'proposal:p2'}
    assert comparison['mode'] == 'rehearsal'
    assert 'selectedBusinessId' not in comparison


def test_explicit_exclusion_and_foreign_evidence_rejected(store):
    ps = proposals(); ps[1]['coverage'].append({'deliverableId': 'booking', 'status': 'excluded', 'detail': 'Reservation integration is excluded from this quote.'})
    deal = {'id': 'd1', 'criteria': criteria(), 'businessIds': [p['businessId'] for p in ps]}
    comparison = compare_deal(store, deal, ps)
    assert next(c for c in comparison['offers'][1]['coverage'] if c['deliverableId'] == 'booking')['status'] == 'excluded'
    ps[0]['comparableProjectIds'] = ['ember-dining']
    with pytest.raises(ValueError):
        compare_deal(store, deal, ps)


def test_live_failure_never_falls_back(store, monkeypatch):
    monkeypatch.setenv('AI_MODE', 'live')
    monkeypatch.setenv('STRANDS_MODEL_MODE', 'direct')
    for key in ('AKAMAI_BASE_URL', 'AKAMAI_API_KEY', 'AKAMAI_MODEL'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(InferenceUnavailable):
        generate_matches(store, criteria())


def test_generic_website_evidence_does_not_prove_compound_must_have(store):
    result = generate_matches(store, criteria(mustHaves=['Responsive website with POS integration and WCAG AA conformance']))
    for match in result['matches']:
        criterion = next(c for c in match['criteria'] if c['id'] == 'must:0')
        assert criterion['status'] == 'partial'
        assert 'POS integration' in criterion['explanation']
        assert 'formal accessibility conformance' in criterion['explanation']


def test_orchestrator_stops_after_validated_tool_output():
    from types import SimpleNamespace
    from backend.matching import AnalysisBudget
    finished = False
    hook = AnalysisBudget(lambda: finished)
    event = SimpleNamespace(cancel=None)
    hook.before_call(event)
    assert event.cancel is None and hook.calls == 1
    finished = True
    hook.before_call(event)
    assert event.cancel == 'Validated analysis is complete.'
    assert hook.calls == 1
