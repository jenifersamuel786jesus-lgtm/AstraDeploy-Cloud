import os
os.environ["DATABASE_URL"] = "sqlite:///./test_astra.db"
from fastapi.testclient import TestClient
from app.main import app, Base, engine

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client = TestClient(app)
def auth(email):
    r = client.post('/api/auth/register', json={'email':email, 'password':'safe-password'})
    assert r.status_code == 201
    return {'Authorization': 'Bearer ' + r.json()['access_token']}
def test_workload_recommendation_and_cost():
    headers = auth('owner@example.com')
    ws = client.post('/api/workspaces', json={'name':'Platform'}, headers=headers).json()
    workload = client.post(f"/api/workspaces/{ws['id']}/workloads", headers=headers, json={'name':'API','requests_per_minute':1500,'latency_ms':80,'availability':99.9}).json()
    assert workload['name'] == 'API'
    recommendation = client.get(f"/api/workspaces/{ws['id']}/workloads/{workload['id']}/recommendation", headers=headers)
    assert recommendation.status_code == 200
    assert recommendation.json()['replicas'] == 2
    cost = client.get(f"/api/workspaces/{ws['id']}/cost-estimate", headers=headers).json()
    assert cost['currency'] == 'USD'
    assert 'assumptions' in cost

def test_workspace_isolation():
    owner = auth('second@example.com')
    ws = client.post('/api/workspaces', json={'name':'Private'}, headers=owner).json()
    stranger = auth('stranger@example.com')
    response = client.get(f"/api/workspaces/{ws['id']}/workloads", headers=stranger)
    assert response.status_code == 403

def test_validation_and_health():
    assert client.get('/api/health').json()['status'] == 'ok'
    headers = auth('validation@example.com')
    ws = client.post('/api/workspaces', json={'name':'Valid'}, headers=headers).json()
    assert client.post(f"/api/workspaces/{ws['id']}/workloads", headers=headers, json={'name':'x','cpu':-1}).status_code == 422
