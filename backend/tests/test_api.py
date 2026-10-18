from fastapi.testclient import TestClient
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
import main
import outcomes
import json

client = TestClient(main.app)

def test_health_endpoint():
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body.get('success') is True or body.get('status') in {'ok', 'online'}

def test_root_endpoint():
    response = client.get('/')
    assert response.status_code == 200
    assert response.json().get('app') == 'ReCoverIQ'

def test_proposals_endpoint_returns_list():
    response = client.get('/api/proposals')
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_outcomes_endpoint_returns_list():
    response = client.get('/api/outcomes')
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_corrupt_outcome_storage_is_not_reported_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, 'OUTCOMES_FILE', tmp_path / 'outcomes.json')
    (tmp_path / 'outcomes.json').write_text('{', encoding='utf-8')
    strict_client = TestClient(main.app, raise_server_exceptions=False)

    response = strict_client.get('/api/outcomes')

    assert response.status_code == 500

def test_evaluate_rejects_invalid_empty_body():
    response = client.post('/api/evaluate', json={})
    assert response.status_code in {400, 422}

def test_cors_allows_configured_local_frontend_origin():
    response = client.options(
        '/api/health',
        headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'GET',
        },
    )
    assert response.headers.get('access-control-allow-origin') == 'http://localhost:5173'

def test_cors_does_not_allow_unconfigured_origin():
    response = client.options(
        '/api/health',
        headers={
            'Origin': 'https://untrusted.example',
            'Access-Control-Request-Method': 'GET',
        },
    )
    assert 'access-control-allow-origin' not in response.headers

def test_outcome_creation_rejects_duplicate_proposal(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, 'OUTCOMES_FILE', tmp_path / 'outcomes.json')
    monkeypatch.setattr(outcomes, 'PROPOSALS_FILE', tmp_path / 'proposals.json')
    (tmp_path / 'proposals.json').write_text(
        json.dumps([{
            'proposal_id': 'PROP-TEST',
            'lot_id': 'LOT-TEST',
            'expected_recovery_inr': 100,
        }]),
        encoding='utf-8',
    )
    payload = {'proposal_id': 'PROP-TEST', 'actual_recovery_inr': 90}

    created = client.post('/api/outcomes', json=payload)
    duplicate = client.post('/api/outcomes', json=payload)

    assert created.status_code == 201
    assert created.json()['actual_recovery_inr'] == 90
    assert duplicate.status_code == 422
    assert 'already recorded' in duplicate.json()['detail']

def test_dataset_import_persists_and_is_returned_by_dataset_api(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'LOTS_FILE', tmp_path / 'lots.json')
    monkeypatch.setattr(main, 'METADATA_FILE', tmp_path / 'dataset_metadata.json')
    payload = {
        'filename': 'lots.csv',
        'lots': [{
            'lot_id': 'LOT-IMPORT-TEST',
            'units': 5,
            'inspection': 'approved',
            'refurbishment_inr': 10,
            'handling_inr': 2,
            'resale_price_inr': 50,
            'scrap_recovery_inr': 3,
        }],
    }

    imported = client.post('/api/lots/import', json=payload)
    dataset = client.get('/api/dataset')

    assert imported.status_code == 201
    assert imported.json()['success'] is True
    assert imported.json()['dataset']['record_count'] == 1
    assert imported.json()['summary']['inventory_value_inr'] == 250
    assert dataset.status_code == 200
    assert dataset.json()['lots'][0]['lot_id'] == 'LOT-IMPORT-TEST'
    assert (tmp_path / 'lots.json').exists()
    assert (tmp_path / 'dataset_metadata.json').exists()

def test_summary_keeps_unknown_inventory_value_null():
    assert main.calculate_dataset_summary([])['inventory_value_inr'] is None

def test_variance_aggregates_legacy_outcomes_consistently(tmp_path, monkeypatch):
    monkeypatch.setattr(outcomes, 'OUTCOMES_FILE', tmp_path / 'outcomes.json')
    monkeypatch.setattr(outcomes, 'PROPOSALS_FILE', tmp_path / 'proposals.json')
    (tmp_path / 'proposals.json').write_text(
        json.dumps([{
            'proposal_id': 'PROP-TEST',
            'lot_id': 'LOT-TEST',
            'expected_recovery_inr': 100,
        }]),
        encoding='utf-8',
    )
    (tmp_path / 'outcomes.json').write_text(
        json.dumps([
            {'proposal_id': 'PROP-TEST', 'actual_recovery_inr': 40},
            {'proposal_id': 'PROP-TEST', 'actual_recovery_inr': 50},
        ]),
        encoding='utf-8',
    )

    response = client.get('/api/proposals/PROP-TEST/variance')
    assert response.status_code == 200
    assert response.json()['actual_recovery_inr'] == 90
    assert response.json()['variance_inr'] == -10
