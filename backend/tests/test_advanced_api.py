import os
os.environ["DATABASE_URL"] = "sqlite:///./advanced_test.db"
from fastapi.testclient import TestClient
from app.main import app, Base, engine
Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client = TestClient(app)
def setup_workspace():
    token = client.post('/api/auth/register', json={'email':'advanced@example.com','password':'safe-password'}).json()['access_token']
    h={'Authorization':f'Bearer {token}'}
    ws=client.post('/api/workspaces',json={'name':'Advanced'},headers=h).json()
    w=client.post(f"/api/workspaces/{ws['id']}/workloads",json={'name':'worker'},headers=h).json()
    return h,ws,w
def test_advanced_records_are_truthful_and_plan_only():
    h,ws,w=setup_workspace(); wid=ws['id']
    assert client.get(f'/api/workspaces/{wid}/providers',headers=h).json()[0]['status']=='disconnected'
    p=client.post(f'/api/workspaces/{wid}/workloads/{w["id"]}/provisioning-plans?provider=aws',headers=h).json()
    assert p['status']=='plan_only' and p['apply_allowed'] is False
    assert 'resource "container_service"' in p['terraform_config']
    assert client.post(f'/api/workspaces/{wid}/metrics',headers=h,json={'metric':'cpu','value':42,'source':'test'}).status_code==201
    assert client.get(f'/api/workspaces/{wid}/monitoring',headers=h).json()['connected'] is True
    assert client.post(f'/api/workspaces/{wid}/alerts',headers=h,json={'title':'Budget review'}).status_code==201
    assert client.get(f'/api/workspaces/{wid}/audit-logs',headers=h).json()
    e=client.post(f'/api/workspaces/{wid}/experiments',headers=h,json={'name':'baseline','dataset_ref':'synthetic://resource-v1','hyperparameters':{'alpha':0.1}}).json()
    assert e['status']=='created'
    m=client.post(f'/api/workspaces/{wid}/models',headers=h,json={'name':'sizer','version':'1.0','artifact_uri':'local://artifact'}).json()
    assert m['lifecycle']=='candidate'
    pipe=client.post(f'/api/workspaces/{wid}/pipelines',headers=h,json={'name':'train','definition':{'steps':['validate','train']}}).json()
    assert pipe['enabled'] is False
