"""Verify the connected fictional campaign speechwriter journey through the API.

Creates three sample provider responses and an explicit buyer preference. No
email, real provider contact, payments, or contractual acceptance occurs.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx


WRITERS = {'campaign-voice', 'civic-script', 'maya-bennett'}
PROJECTS = {'campaign-voice': 'governor-campaign', 'civic-script': 'mayor-announcements', 'maya-bennett': 'lead-together'}


def campaign_criteria():
    """Keep the requirements and stable deliverable IDs aligned with lib/demo.ts."""
    return {
        'inspirationProjectIds': ['governor-campaign'],
        'serviceCategory': 'Speechwriting',
        'description': 'Prepared sample comparison — legislative speechwriter. We need a researched ten-minute speech, a short event introduction, two rounds of revisions, and a rehearsal session for a fictional legislative election campaign. Relevant completed election campaign speechwriting is our strongest preference. Compare municipal office announcements and keynote speaking as related experience.',
        'budgetCents': 600000, 'currency': 'USD',
        'deliverables': [
            {'id': 'speech', 'label': 'Speechwriting for a ten-minute speech', 'mandatory': True},
            {'id': 'research', 'label': 'Speech research and source notes', 'mandatory': True},
            {'id': 'intro', 'label': 'Short event introduction', 'mandatory': True},
            {'id': 'revisions', 'label': 'Two rounds of speech revisions', 'mandatory': True},
            {'id': 'rehearsal', 'label': 'Speaker coaching and rehearsal support', 'mandatory': True},
        ],
        'keywords': ['campaign speechwriting', 'election campaign experience'],
        'mustHaves': [],
        'desiredStandard': 'Clear, carefully researched writing in the speaker’s own voice. Give the greatest weight to comparable completed election campaign work.',
        'location': '', 'deliveryMode': 'remote', 'targetDate': None,
        'buyerName': 'Prepared sample campaign team', 'preferencesConfirmed': True,
    }


def sample_response(business_id, criteria):
    samples = {
        'campaign-voice': (4800, 'Three weeks', 'Our fictional completed governor campaign speechwriting provides comparable election campaign experience. The election result is context, not proof of a causal effect or a promise of a future result.'),
        'civic-script': (3400, 'Two weeks', 'Our fictional mayor’s office announcements demonstrate concise official writing and revisions. The available portfolio does not establish election campaign speechwriting.'),
        'maya-bennett': (3900, 'Three weeks', 'Our completed keynote work demonstrates speech structure, delivery, and coaching. Applying it to campaign speechwriting needs discussion; the portfolio does not establish prior electoral campaign writing.'),
    }
    price, duration, fit = samples[business_id]
    return {
        'price': price, 'currency': 'USD',
        'scope': 'Fictional fixed-price demo quote for one researched ten-minute speech, source notes, a short event introduction, two consolidated revision rounds, and one 60-minute remote rehearsal. Additional speeches and revisions require a separate quote.',
        'timeline': duration + ' after approved source material is supplied, with two review rounds and one remote rehearsal.',
        'fitStatement': fit,
        'approach': 'Review approved source material, agree an outline, draft, review with the customer, revise, and rehearse. The customer approves all facts and final text.',
        'coverage': [{'deliverableId': item['id'], 'status': 'included', 'detail': 'Included in this fictional fixed-price sample scope.'}
                     for item in criteria['deliverables']],
        'exclusions': ['Additional speeches or revision rounds', 'On-site attendance', 'Any guarantee of an election result'],
        'assumptions': ['Customer supplies approved facts and one decision-maker.', 'Feedback is consolidated within two working days.'],
        'clarifications': ['Confirm event timing and the approval process.'],
        'comparableProjectIds': [PROJECTS[business_id]], 'achievementIds': [],
    }


def run(api, preview_credentials=None):
    auth = None
    if preview_credentials:
        credentials = json.loads(Path(preview_credentials).read_text())
        auth = httpx.BasicAuth(credentials['username'], credentials['password'])
    with httpx.Client(base_url=api.rstrip('/'), timeout=180, auth=auth) as client:
        def call(method, path, actor=None, body=None, expected=200):
            response = client.request(method, path, headers=actor, **({'json': body} if body is not None else {}))
            assert response.status_code == expected, f'{method} {path}: HTTP {response.status_code}'
            return response.json()

        def session(role='buyer', business_id=None):
            body = {'role': role, **({'businessId': business_id} if business_id else {})}
            token = call('POST', '/sessions', body=body)['token']
            # Keep the preview's Basic Authorization header intact.
            return {'X-DealFeed-Authorization': 'Bearer ' + token}

        def wait_for_match(response, actor):
            assert response.status_code in (201, 202), f'Matching returned HTTP {response.status_code}'
            result = response.json()
            deadline = time.monotonic() + 190
            while result.get('status') != 'complete' and time.monotonic() < deadline:
                time.sleep(2)
                result = call('GET', '/matches/' + result.get('jobId', result.get('id', '')), actor)
            assert result.get('status') == 'complete', 'Matching did not complete within the verification deadline.'
            return result

        started = time.monotonic()
        health = call('GET', '/health')
        buyer, other_buyer = session(), session()
        criteria = campaign_criteria()
        match_started = time.monotonic()
        match = wait_for_match(client.post('/matches', headers=buyer, json={'criteria': criteria}), buyer)
        match_seconds = round(time.monotonic() - match_started, 2)
        ids = [row['businessId'] for row in match['matches']]
        assert len(ids) == 3 and set(ids) == WRITERS, 'Expected the two speechwriters and related keynote speaker.'
        assert ids[0] == 'campaign-voice', 'Comparable completed campaign experience should lead for this brief.'
        for row in match['matches']:
            expected = 'direct' if row['businessId'] == 'campaign-voice' else 'related'
            assert row['experienceFit']['level'] == expected
            assert not any(source['kind'] == 'website' for source in row['evidence']), 'This verifies the portfolio-only campaign scenario.'
            assert any(source['kind'] == 'completed_project' for source in row['evidence'])
        assert call('GET', '/requests', buyer)['requests'] == []
        call('GET', '/matches/' + match['id'], other_buyer, expected=404)
        for id_ in ids:
            profile = call('GET', '/businesses/' + id_)
            # Public profile endpoints may wrap the record.
            business = profile.get('business', profile)
            assert business['profile']['lead']['name'] and business['profile']['process']
        assert call('GET', '/requests', buyer)['requests'] == [], 'Profile exploration must not send invitations.'
        approval = {'matchRunId': match['id'], 'businessIds': ids, 'approved': True, 'idempotencyKey': str(uuid4())}
        deal = call('POST', '/deals', buyer, approval, 201)
        repeated = call('POST', '/deals', buyer, approval, 201)
        assert repeated['id'] == deal['id'] and len(repeated['requests']) == 3
        assert all(request['approvedBrief'] == criteria for request in deal['requests'])
        call('GET', '/deals/' + deal['id'], other_buyer, expected=404)
        for index, request in enumerate(deal['requests']):
            provider = session('provider', request['businessId'])
            inbox = call('GET', '/requests', provider)['requests']
            assert any(row['id'] == request['id'] for row in inbox)
            assert all(row['businessId'] == request['businessId'] for row in inbox)
            call('GET', '/deals/' + deal['id'], provider, expected=403)
            proposal = sample_response(request['businessId'], criteria)
            another = deal['requests'][(index + 1) % 3]
            call('POST', f"/requests/{another['id']}/proposal", provider, proposal, 404)
            call('POST', f"/requests/{request['id']}/proposal", provider, proposal, 201)
            call('POST', f"/requests/{request['id']}/proposal", provider, proposal, 409)
        compare_started = time.monotonic()
        response = client.post('/deals/' + deal['id'] + '/compare', headers=buyer, json={})
        assert response.status_code in (200, 202), f'Comparison returned HTTP {response.status_code}'
        comparison = response.json() if response.status_code == 200 else None
        deadline = time.monotonic() + 190
        while comparison is None and time.monotonic() < deadline:
            time.sleep(2)
            refreshed = call('GET', '/deals/' + deal['id'], buyer)
            assert refreshed.get('comparisonStatus') != 'failed', 'Comparison inference failed; saved responses remain available.'
            comparison = refreshed.get('comparison')
        assert comparison is not None, 'Comparison did not finish within the verification deadline.'
        compare_seconds = round(time.monotonic() - compare_started, 2)
        assert comparison['mode'] == match['mode'] and len(comparison['offers']) == 3
        assert comparison['pendingBusinessIds'] == []
        finding = next(row for row in comparison['findings'] if row['id'] == 'difference:experience')
        assert set(finding['businessIds']) == WRITERS and 'project:governor-campaign' in finding['evidenceIds']
        offers = {offer['businessId']: offer for offer in comparison['offers']}
        assert offers['campaign-voice']['demonstratedFit']['experienceFit']['level'] == 'direct'
        assert offers['campaign-voice']['cheapestDifferenceCents'] == 140000
        assert all(row['status'] == 'included' for offer in offers.values() for row in offer['coverage'])
        assert 'selectedBusinessId' not in comparison
        if match['mode'] == 'akamai+strands':
            assert any(row.get('semanticInsights') for row in match['matches'])
            assert comparison['semanticInsights']
        chosen = next(request['id'] for request in deal['requests'] if request['businessId'] == 'campaign-voice')
        selected = call('POST', '/deals/' + deal['id'] + '/selection', buyer, {'requestId': chosen})
        assert selected['selectedRequestId'] == chosen
        reloaded = call('GET', '/deals/' + deal['id'], buyer)
        assert reloaded['selectedRequestId'] == chosen and len(reloaded['proposals']) == 3
        assert reloaded.get('comparison'), 'Comparison must persist after the preference is saved.'
        return {
            'status': 'passed', 'verifiedAt': datetime.now(timezone.utc).isoformat(),
            'api': api, 'health': health, 'mode': match['mode'], 'comparisonMode': comparison['mode'],
            'businessCount': 3, 'proposalCount': 3, 'dealId': deal['id'],
            'rankedBusinessIds': ids, 'experienceLevels': {row['businessId']: row['experienceFit']['level'] for row in match['matches']},
            'websiteEvidenceCount': 0, 'experienceFindingId': finding['id'],
            'checks': ['portfolio-only matching without website evidence', 'campaign experience ranks first',
                       'municipal and keynote experience remains related', 'full profiles available',
                       'analysis and exploration send no invitations', 'atomic idempotent approval',
                       'three independent reviewed sample responses', 'cross-buyer and provider isolation',
                       'duplicate proposal rejection', 'grounded experience comparison',
                       'comparison persistence', 'explicit persisted preference'],
            'matchSeconds': match_seconds, 'comparisonSeconds': compare_seconds,
            'elapsedSeconds': round(time.monotonic() - started, 2),
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--report', help='Optional verification report path. No credentials or session tokens are stored.')
    parser.add_argument('--preview-credentials', help='Ignored JSON file containing the private preview username and password.')
    arguments = parser.parse_args()
    report = run(arguments.api, arguments.preview_credentials)
    if arguments.report:
        Path(arguments.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
