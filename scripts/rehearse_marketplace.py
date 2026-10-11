"""Exercise the connected marketplace using explicitly fictional demo accounts.

Run while the API serves: .venv/bin/python -m scripts.rehearse_marketplace
No email, real provider contact, payments, or contractual acceptance occurs.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx


def run(api):
    with httpx.Client(base_url=api.rstrip('/'), timeout=180) as client:
        def session(role='buyer', business=None):
            data = {'role': role}
            if business:
                data['businessId'] = business
            response = client.post('/sessions', json=data)
            response.raise_for_status()
            return {'Authorization': 'Bearer ' + response.json()['token']}

        def call(method, path, user, body=None, expected=200):
            response = client.request(method, path, headers=user, **({'json': body} if body is not None else {}))
            assert response.status_code == expected, f'{method} {path}: {response.status_code} {response.text[:500]}'
            return response.json()

        started = time.monotonic()
        health = client.get('/health').json()
        buyer, other_buyer = session(), session()
        criteria = {
            'inspirationProjectIds': ['poppy-web'],
            'description': 'Create a warm restaurant website with mobile menus, a reservation service integration, and an editable content management system. We supply copy and photos.',
            'serviceCategory': 'Website development', 'budgetCents': 600000, 'currency': 'USD',
            'deliverables': [
                {'id': 'website', 'label': 'Responsive restaurant website', 'mandatory': True},
                {'id': 'reservations', 'label': 'Reservation integration', 'mandatory': True},
                {'id': 'menus', 'label': 'Editable seasonal menus', 'mandatory': False},
            ],
            'keywords': ['warm', 'restaurant'], 'mustHaves': ['Reservation integration'],
            'desiredStandard': 'Warm design with clear mobile menus', 'location': 'Kansas City',
            'deliveryMode': 'remote', 'targetDate': str(date.today() + timedelta(days=60)),
            'buyerName': 'Prepared sample restaurant', 'preferencesConfirmed': True,
        }
        response = client.post('/matches', headers=buyer, json={'criteria': criteria})
        assert response.status_code in (201, 202), response.text
        match = response.json()
        if response.status_code == 202:
            for _ in range(90):
                time.sleep(2)
                match = call('GET', '/matches/' + match['jobId'] if 'jobId' in match else '/matches/' + match['id'], buyer)
                if match.get('status') == 'complete':
                    break
        assert match.get('status') == 'complete', 'Matching did not complete.'
        ids = [item['businessId'] for item in match['matches']]
        assert len(ids) == len(set(ids)) == 5, f'Expected five supported website businesses, got {len(ids)}.'
        assert call('GET', '/requests', buyer)['requests'] == [], 'Analysis must not send invitations.'
        call('GET', '/matches/' + match['id'], other_buyer, expected=404)
        for business_id in ids:
            assert client.get('/businesses/' + business_id).status_code == 200
        assert call('GET', '/requests', buyer)['requests'] == [], 'Exploration must not contact providers.'
        approval = {'matchRunId': match['id'], 'businessIds': ids, 'approved': True, 'idempotencyKey': str(uuid4())}
        deal = call('POST', '/deals', buyer, approval, 201)
        repeated = call('POST', '/deals', buyer, approval, 201)
        assert repeated['id'] == deal['id'] and len(repeated['requests']) == 5
        assert all(row['approvedBrief'] == criteria for row in deal['requests'])
        call('GET', '/deals/' + deal['id'], other_buyer, expected=404)
        for index, request in enumerate(deal['requests']):
            provider = session('provider', request['businessId'])
            inbox = call('GET', '/requests', provider)['requests']
            assert any(row['id'] == request['id'] for row in inbox)
            assert all(row['businessId'] == request['businessId'] for row in inbox)
            call('GET', '/deals/' + deal['id'], provider, expected=403)
            another = deal['requests'][(index + 1) % len(deal['requests'])]
            proposal = {
                'price': 4200 + index * 300, 'currency': 'USD',
                'scope': 'A responsive restaurant website with seasonal menus. Customer supplies copy and photography.',
                'timeline': f'{4 + index} weeks after receiving content',
                'fitStatement': 'Prepared sample response: our restaurant portfolio shows responsive menus and reservation integrations.',
                'approach': 'Confirm content, design mobile layouts, implement, test, and hand over editing access.',
                'coverage': [
                    {'deliverableId': 'website', 'status': 'included', 'detail': 'Responsive website design and implementation.'},
                    {'deliverableId': 'reservations', 'status': 'excluded' if index == 0 else 'included', 'detail': 'Reservation integration excluded from this sample quote.' if index == 0 else 'Connect the existing reservation service.'},
                ],
                'exclusions': ['Reservation integration'] if index == 0 else [],
                'assumptions': ['Buyer supplies copy and photography.'], 'clarifications': ['Confirm reservation account access.'],
            }
            call('POST', f"/requests/{another['id']}/proposal", provider, proposal, 404)
            call('POST', f"/requests/{request['id']}/proposal", provider, proposal, 201)
            call('POST', f"/requests/{request['id']}/proposal", provider, proposal, 409)
        response = client.post('/deals/' + deal['id'] + '/compare', headers=buyer, json={})
        assert response.status_code in (200, 202), response.text
        comparison = response.json()
        if response.status_code == 202:
            for _ in range(90):
                time.sleep(2)
                refreshed = call('GET', '/deals/' + deal['id'], buyer)
                if refreshed.get('comparison'):
                    comparison = refreshed['comparison']
                    break
        chosen = deal['requests'][1]['id']
        selected = call('POST', '/deals/' + deal['id'] + '/selection', buyer, {'requestId': chosen})
        assert selected['selectedRequestId'] == chosen
        reloaded = call('GET', '/deals/' + deal['id'], buyer)
        assert reloaded['selectedRequestId'] == chosen and len(reloaded['proposals']) == 5
        assert reloaded.get('comparison'), 'Comparison must remain available after selection.'
        return {'status': 'passed', 'api': api, 'health': health, 'mode': match['mode'],
                'businessCount': len(ids), 'proposalCount': 5, 'dealId': deal['id'],
                'checks': ['five distinct matches', 'analysis/exploration sends no invitations', 'atomic idempotent approval',
                           'five independent provider submissions', 'cross-buyer and provider isolation',
                           'duplicate proposal rejection', 'comparison persistence', 'explicit persisted preference'],
                'comparisonMode': comparison.get('mode'), 'elapsedSeconds': round(time.monotonic() - started, 2)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--report', help='Optional JSON verification report path (no tokens stored).')
    arguments = parser.parse_args()
    report = run(arguments.api)
    if arguments.report:
        Path(arguments.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
