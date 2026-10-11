"""Acceptance checks for portfolio-led speechwriting and proposal comparison."""
from copy import deepcopy

import pytest

from backend import matching, research
from backend.models import MatchCriteria
from backend.store import Store


WRITERS = {'campaign-voice', 'civic-script', 'maya-bennett'}


def campaign_criteria(**changes):
    return {
        'inspirationProjectIds': ['governor-campaign'],
        'description': 'Find a speechwriter for a legislative election campaign. Prior campaign speechwriting experience is especially relevant.',
        'serviceCategory': 'Speechwriting', 'budgetCents': 600000, 'currency': 'USD',
        'deliverables': [
            {'id': 'speech', 'label': 'Speechwriting for a ten-minute speech', 'mandatory': True},
            {'id': 'research', 'label': 'Speech research and source notes', 'mandatory': True},
            {'id': 'intro', 'label': 'Short event introduction', 'mandatory': True},
            {'id': 'revisions', 'label': 'Two rounds of speech revisions', 'mandatory': True},
            {'id': 'rehearsal', 'label': 'Speaker coaching and rehearsal support', 'mandatory': True},
        ],
        'keywords': ['campaign speechwriting', 'election campaign experience'],
        'mustHaves': [], 'desiredStandard': '', 'deliveryMode': 'remote',
        'location': '', **changes,
    }


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_MODE', 'rehearsal')
    return Store(str(tmp_path / 'campaign.sqlite'))


def remove_websites(store):
    for business in store.list('business'):
        store.put('business', {**business, 'website': '', 'researchUrls': [], 'researchFixtures': []})


def mock_live_orchestrator(monkeypatch):
    """Exercise the live tool/validation path without making inference calls."""
    monkeypatch.setenv('AI_MODE', 'live')
    monkeypatch.setenv('STRANDS_MODEL_MODE', 'direct')

    def orchestrate(tools, system, task, complete):
        available = {tool.tool_name: tool for tool in tools}
        if 'retrieve_matching_evidence' in available:
            context = available['retrieve_matching_evidence']()
            # A model's preference for a less relevant provider cannot erase
            # completed campaign experience from the final recommendation.
            ids = [business['id'] for business in context['businesses']]
            ids.sort(key=lambda id_: id_ == 'campaign-voice')
            available['produce_validated_match_analysis'](ids, [{
                'detail': 'The completed campaign speechwriting project suggests directly relevant experience for this legislative campaign brief; exact scope still needs confirmation.',
                'evidenceIds': ['project:governor-campaign'],
            }])
        else:
            context = available['analyze_submitted_proposals']()
            available['produce_validated_comparison'](
                [finding['id'] for finding in context['findings']], [{
                    'detail': 'Prior completed campaign speechwriting suggests closer experience for this brief. The municipal writer and keynote speaker offer related work whose exact scope should be confirmed.',
                    'evidenceIds': ['project:governor-campaign', 'project:mayor-announcements', 'project:lead-together'],
                }],
            )
        assert complete()

    monkeypatch.setattr(matching, '_orchestrator', orchestrate)


def sample_proposals():
    projects = {'campaign-voice': 'governor-campaign', 'civic-script': 'mayor-announcements', 'maya-bennett': 'lead-together'}
    prices = {'campaign-voice': 4800, 'civic-script': 3400, 'maya-bennett': 3900}
    return [{
        'id': 'proposal-' + id_, 'requestId': 'request-' + id_, 'dealId': 'campaign-deal',
        'businessId': id_, 'price': prices[id_], 'currency': 'USD',
        'timeline': 'Three weeks after approved source material is supplied',
        'fitStatement': 'Fictional provider-authored response; review our completed work and confirm the scope.',
        'approach': 'Review approved source material, draft, revise, and rehearse with the customer.',
        'scope': 'Prepared sample quote for speechwriting, a short introduction, and one rehearsal session.',
        'coverage': [{'deliverableId': item['id'], 'status': 'included', 'detail': 'Included in this fictional sample quote.'}
                     for item in campaign_criteria()['deliverables']],
        'comparableProjectIds': [projects[id_]],
    } for id_ in ('civic-script', 'maya-bennett', 'campaign-voice')]


def assert_campaign_fit(result):
    matches = result['matches']
    assert {match['businessId'] for match in matches} == WRITERS
    assert matches[0]['businessId'] == 'campaign-voice'
    assert matches[0]['experienceFit']['level'] == 'direct'
    assert 'project:governor-campaign' in matches[0]['experienceFit']['evidenceIds']
    assert all(match['experienceFit']['level'] == 'related' for match in matches[1:])
    for match in matches:
        assert any(criterion['id'] == 'experience' for criterion in match['criteria'])
        source_by_id = {source['id']: source for source in match['evidence']}
        for source_id in match['experienceFit']['evidenceIds']:
            source = source_by_id[source_id]
            assert source['kind'] == 'completed_project'
            assert source['businessId'] == match['businessId']
            assert source['provenance'] == 'sample'
        assert not any(source['kind'] == 'website' for source in match['evidence'])


@pytest.mark.parametrize('live', [False, True], ids=['rehearsal', 'mocked-live'])
@pytest.mark.parametrize('website_state', ['absent', 'fetch-failed'])
def test_campaign_match_and_comparison_complete_without_website_evidence(store, monkeypatch, live, website_state):
    remove_websites(store)
    if live:
        mock_live_orchestrator(monkeypatch)
    fetches = []
    if website_state == 'fetch-failed':
        for id_ in WRITERS:
            business = store.get('business', id_)
            url = 'https://portfolio.example.org/' + id_
            store.put('business', {**business, 'website': url, 'researchUrls': [url]})

        def unavailable(url, hosts):
            fetches.append(url)
            raise TimeoutError('Simulated unavailable public portfolio')

        monkeypatch.setattr(research, 'fetch_public_page', unavailable)
    else:
        def unexpected_fetch(*args, **kwargs):
            raise AssertionError('A business without a website should not trigger a fetch')
        monkeypatch.setattr(research, 'fetch_public_page', unexpected_fetch)

    criteria = MatchCriteria.model_validate(campaign_criteria()).model_dump(mode='json')
    result = matching.generate_matches(store, criteria)
    assert_campaign_fit(result)
    assert result['mode'] == ('akamai+strands' if live else 'rehearsal')
    if website_state == 'fetch-failed':
        assert len(fetches) == 3
        assert all(row['status'] == 'unavailable' for row in store.list('research'))
    proposals = sample_proposals()
    comparison = matching.compare_deal(store, {'id': 'campaign-deal', 'criteria': criteria, 'businessIds': sorted(WRITERS)}, proposals)
    assert comparison['mode'] == result['mode']
    assert len(comparison['offers']) == 3 and not comparison['pendingBusinessIds']
    assert 'selectedBusinessId' not in comparison
    by_business = {offer['businessId']: offer for offer in comparison['offers']}
    assert by_business['campaign-voice']['demonstratedFit']['experienceFit']['level'] == 'direct'
    assert by_business['campaign-voice']['cheapestDifferenceCents'] == 140000
    finding = next(finding for finding in comparison['findings'] if finding['id'] == 'difference:experience')
    assert set(finding['businessIds']) == WRITERS
    assert 'project:governor-campaign' in finding['evidenceIds']
    if live:
        assert result['matches'][0]['semanticInsights']
        assert comparison['semanticInsights']
        assert all(insight['label'] == 'AI inference' for insight in comparison['semanticInsights'])


def test_experience_advantage_follows_the_requested_work(store):
    remove_websites(store)
    campaign = matching.generate_matches(store, campaign_criteria())
    municipal = matching.generate_matches(store, campaign_criteria(
        inspirationProjectIds=['mayor-announcements'],
        description='Write short official announcements for a mayor and municipal office. Government communications experience is the relevant background.',
        keywords=['government communications', 'short announcements'],
        deliverables=[{'id': 'announcements', 'label': 'Short announcements', 'mandatory': True}],
    ))
    keynote = matching.generate_matches(store, campaign_criteria(
        inspirationProjectIds=['lead-together'], serviceCategory='Keynote speaking',
        description='Provide keynote delivery for a leadership conference with a rehearsal session.',
        keywords=['keynote delivery'],
        deliverables=[{'id': 'keynote', 'label': 'Keynote delivery', 'mandatory': True}],
    ))
    assert campaign['matches'][0]['businessId'] == 'campaign-voice'
    assert municipal['matches'][0]['businessId'] == 'civic-script'
    assert keynote['matches'][0]['businessId'] == 'maya-bennett'


@pytest.mark.parametrize('change', [
    {'archived': True}, {'status': 'in_progress'}, {'visibility': 'private'},
    {'completed': False}, {'publicShareable': False},
])
def test_campaign_experience_requires_public_completed_owned_work(store, change):
    for project in store.list('project'):
        if project['businessId'] == 'campaign-voice':
            store.put('project', {**project, **change})
    result = matching.generate_matches(store, campaign_criteria(inspirationProjectIds=['mayor-announcements']))
    assert 'campaign-voice' not in {match['businessId'] for match in result['matches']}
    assert all(match['experienceFit']['level'] != 'direct' for match in result['matches'])


def test_profile_claim_cannot_substitute_for_completed_campaign_evidence(store):
    for project in store.list('project'):
        if project['businessId'] == 'campaign-voice':
            store.put('project', {**project, 'capabilities': ['speechwriting', 'speech research', 'speech revisions'],
                                 'description': 'Completed general speechwriting, with research and revisions.'})
    result = matching.generate_matches(store, campaign_criteria())
    campaign = next(match for match in result['matches'] if match['businessId'] == 'campaign-voice')
    assert campaign['experienceFit']['level'] != 'direct'
    # Its unchanged, richer business profile and achievements are not proof of
    # a campaign capability absent from the owned completed work metadata.
    assert store.get('business', 'campaign-voice')['profile']['experience']


def test_campaign_experience_is_evidence_based_not_a_business_id_rule(store):
    original = store.get('business', 'campaign-voice')
    renamed = {**deepcopy(original), 'id': 'renamed-writer', 'name': 'New Name Writing Practice'}
    store.put('business', {**original, 'archived': True})
    store.put('business', renamed)
    for project in store.list('project'):
        if project['businessId'] == 'campaign-voice':
            store.put('project', {**project, 'businessId': renamed['id']})
    result = matching.generate_matches(store, campaign_criteria())
    assert result['matches'][0]['businessId'] == renamed['id']
    assert result['matches'][0]['experienceFit']['level'] == 'direct'


def test_campaign_experience_never_overrides_a_budget_conflict(store):
    business = store.get('business', 'campaign-voice')
    store.put('business', {**business, 'minimumProjectCents': 600001})
    result = matching.generate_matches(store, campaign_criteria())
    assert 'campaign-voice' not in {match['businessId'] for match in result['matches']}
    assert any(row['businessId'] == 'campaign-voice' and any('budget' in reason.lower() for reason in row['reasons'])
               for row in result['excluded'])


def test_unproven_speechwriting_requirement_remains_unknown(store):
    result = matching.generate_matches(store, campaign_criteria(mustHaves=['Certified live simultaneous interpretation']))
    for match in result['matches']:
        assessment = next(row for row in match['criteria'] if row['id'] == 'must:0')
        assert assessment['status'] == 'unknown' and assessment['evidenceIds'] == []
