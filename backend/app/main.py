import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./astradeploy.db")
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-me")
ALGORITHM = "HS256"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")
class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    workloads: Mapped[list["Workload"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
class Workload(Base):
    __tablename__ = "workloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    workload_type: Mapped[str] = mapped_column(String(40), default="web")
    environment: Mapped[str] = mapped_column(String(20), default="development")
    cpu: Mapped[float] = mapped_column(Float, default=1)
    memory_gb: Mapped[float] = mapped_column(Float, default=2)
    storage_gb: Mapped[float] = mapped_column(Float, default=20)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=100)
    latency_ms: Mapped[int] = mapped_column(Integer, default=500)
    availability: Mapped[float] = mapped_column(Float, default=99.0)
    budget_usd: Mapped[float] = mapped_column(Float, default=100)
    region: Mapped[str] = mapped_column(String(80), default="unspecified")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    workspace: Mapped[Workspace] = relationship(back_populates="workloads")
class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
class Token(BaseModel): access_token: str; token_type: str
class WorkspaceCreate(BaseModel): name: str = Field(min_length=2, max_length=120)
class WorkspaceOut(BaseModel): model_config = ConfigDict(from_attributes=True); id: int; name: str
class WorkloadIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    workload_type: str = "web"
    environment: str = "development"
    cpu: float = Field(default=1, gt=0, le=256)
    memory_gb: float = Field(default=2, gt=0, le=2048)
    storage_gb: float = Field(default=20, ge=0, le=100000)
    requests_per_minute: int = Field(default=100, ge=0)
    latency_ms: int = Field(default=500, gt=0)
    availability: float = Field(default=99.0, ge=90, le=99.999)
    budget_usd: float = Field(default=100, ge=0)
    region: str = "unspecified"
class WorkloadOut(WorkloadIn): model_config = ConfigDict(from_attributes=True); id: int; workspace_id: int

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
def db():
    s = SessionLocal()
    try: yield s
    finally: s.close()
def token_for(user: User): return jwt.encode({"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, JWT_SECRET, algorithm=ALGORITHM)
def current_user(token: str = Depends(oauth2), session: Session = Depends(db)):
    cred = HTTPException(status_code=401, detail="Invalid authentication credentials", headers={"WWW-Authenticate":"Bearer"})
    try: uid = int(jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM]).get("sub"))
    except (JWTError, TypeError, ValueError): raise cred
    user = session.get(User, uid)
    if not user: raise cred
    return user
def member_workspace(workspace_id: int, user: User, session: Session):
    if not session.scalar(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)):
        raise HTTPException(403, "You do not have access to this workspace")
def recommendation(w: Workload):
    cpu = max(0.5, w.cpu, w.requests_per_minute / 500)
    memory = max(1, w.memory_gb, cpu * 1.5)
    if w.latency_ms < 100: cpu *= 1.5
    if w.availability >= 99.9: replicas, scaling = 2, "horizontal autoscaling with multi-zone replicas"
    elif w.requests_per_minute > 1000: replicas, scaling = 2, "horizontal autoscaling"
    else: replicas, scaling = 1, "vertical sizing; add autoscaling when utilization is observed"
    monthly = cpu * 18 + memory * 4.5 + w.storage_gb * 0.10
    return {"recommended_cpu": round(cpu, 2), "recommended_memory_gb": round(memory, 2), "replicas": replicas, "scaling_strategy": scaling, "estimated_monthly_usd": round(monthly * replicas, 2), "pricing_source": "user-transparent baseline assumption: $18/vCPU-month, $4.50/GB-month, $0.10/storage-GB-month", "explanation": "Deterministic sizing uses request volume, stated latency, availability, and requested resources. It is not an ML prediction.", "assumptions": ["Sustained average utilization is unknown", "Network, provider discounts, and managed-service fees are excluded", "Estimate is not a billed cost"]}

app = FastAPI(title="AstraDeploy API", version="0.1.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
@app.on_event("startup")
def startup(): Base.metadata.create_all(engine)
@app.get("/api/health")
def health(): return {"status":"ok", "service":"astradeploy-api", "telemetry":"No telemetry source connected"}
@app.post("/api/auth/register", response_model=Token, status_code=201)
def register(data: UserCreate, session: Session = Depends(db)):
    if session.scalar(select(User).where(User.email == data.email.lower().strip())): raise HTTPException(409, "Email already registered")
    user = User(email=data.email.lower().strip(), password_hash=pwd.hash(data.password)); session.add(user); session.commit(); session.refresh(user)
    return {"access_token": token_for(user), "token_type":"bearer"}
@app.post("/api/auth/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(db)):
    user = session.scalar(select(User).where(User.email == form.username.lower().strip()))
    if not user or not pwd.verify(form.password, user.password_hash): raise HTTPException(401, "Incorrect email or password")
    return {"access_token": token_for(user), "token_type":"bearer"}
@app.get("/api/workspaces", response_model=list[WorkspaceOut])
def workspaces(user: User = Depends(current_user), session: Session = Depends(db)):
    return list(session.scalars(select(Workspace).join(Membership).where(Membership.user_id == user.id)).all())
@app.post("/api/workspaces", response_model=WorkspaceOut, status_code=201)
def create_workspace(data: WorkspaceCreate, user: User = Depends(current_user), session: Session = Depends(db)):
    w = Workspace(name=data.name); session.add(w); session.flush(); session.add(Membership(user_id=user.id, workspace_id=w.id, role="owner")); session.commit(); session.refresh(w); return w
@app.get("/api/workspaces/{workspace_id}/workloads", response_model=list[WorkloadOut])
def list_workloads(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    member_workspace(workspace_id, user, session); return list(session.scalars(select(Workload).where(Workload.workspace_id == workspace_id).order_by(Workload.created_at.desc())).all())
@app.post("/api/workspaces/{workspace_id}/workloads", response_model=WorkloadOut, status_code=201)
def create_workload(workspace_id: int, data: WorkloadIn, user: User = Depends(current_user), session: Session = Depends(db)):
    member_workspace(workspace_id, user, session); w = Workload(workspace_id=workspace_id, **data.model_dump()); session.add(w); session.add(AuditEvent(workspace_id=workspace_id, user_id=user.id, action="workload.created")); session.commit(); session.refresh(w); return w
@app.get("/api/workspaces/{workspace_id}/workloads/{workload_id}/recommendation")
def get_recommendation(workspace_id: int, workload_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    member_workspace(workspace_id, user, session); w = session.scalar(select(Workload).where(Workload.id == workload_id, Workload.workspace_id == workspace_id))
    if not w: raise HTTPException(404, "Workload not found")
    return recommendation(w)
@app.get("/api/workspaces/{workspace_id}/cost-estimate")
def cost_estimate(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    member_workspace(workspace_id, user, session); items = list(session.scalars(select(Workload).where(Workload.workspace_id == workspace_id)).all())
    recs = [recommendation(w) for w in items]; total = round(sum(r["estimated_monthly_usd"] for r in recs), 2)
    return {"currency":"USD", "estimated_monthly_total":total, "workloads": [{"name":w.name,"estimate_usd":r["estimated_monthly_usd"]} for w,r in zip(items,recs)], "assumptions":"Baseline user-transparent pricing; not actual billed cost."}

# Advanced platform foundation: records are persisted only when supplied by a connected source or user action.
class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="disconnected")
    region: Mapped[str] = mapped_column(String(80), default="unspecified")
    account_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class ProvisioningPlan(Base):
    __tablename__ = "provisioning_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workload_id: Mapped[int] = mapped_column(ForeignKey("workloads.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20), default="none")
    status: Mapped[str] = mapped_column(String(30), default="plan_only")
    terraform_config: Mapped[str] = mapped_column(Text, default="")
    cost_note: Mapped[str] = mapped_column(Text, default="Cost requires verified provider pricing")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workload_id: Mapped[int | None] = mapped_column(ForeignKey("workloads.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(20), default="none")
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    external_id: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class MetricObservation(Base):
    __tablename__ = "metric_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workload_id: Mapped[int | None] = mapped_column(ForeignKey("workloads.id", ondelete="SET NULL"), nullable=True)
    metric: Mapped[str] = mapped_column(String(80)); value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(120)); observed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class CostObservation(Base):
    __tablename__ = "cost_observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workload_id: Mapped[int | None] = mapped_column(ForeignKey("workloads.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[float] = mapped_column(Float); currency: Mapped[str] = mapped_column(String(8), default="USD")
    source: Mapped[str] = mapped_column(String(120)); observed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info"); title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="open"); details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160)); dataset_ref: Mapped[str] = mapped_column(String(300), default="")
    hyperparameters: Mapped[str] = mapped_column(Text, default="{}"); metrics: Mapped[str] = mapped_column(Text, default="{}"); status: Mapped[str] = mapped_column(String(30), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160)); version: Mapped[str] = mapped_column(String(60)); artifact_uri: Mapped[str] = mapped_column(String(500), default="")
    lifecycle: Mapped[str] = mapped_column(String(30), default="candidate"); evaluation: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
class Pipeline(Base):
    __tablename__ = "pipelines"
    id: Mapped[int] = mapped_column(primary_key=True); workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160)); definition: Mapped[str] = mapped_column(Text, default="{}"); enabled: Mapped[bool] = mapped_column(Boolean, default=False)
class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(primary_key=True); pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued"); logs: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class NameIn(BaseModel): name: str = Field(min_length=2, max_length=160)
class ProviderIn(BaseModel): provider: str; region: str = "unspecified"; account_id: str = ""
class MetricIn(BaseModel): metric: str; value: float; source: str
class CostIn(BaseModel): amount: float = Field(ge=0); currency: str = "USD"; source: str
class AlertIn(BaseModel): severity: str = "info"; title: str; details: str = ""
class ExperimentIn(BaseModel): name: str; dataset_ref: str = ""; hyperparameters: dict = {}
class ModelIn(BaseModel): name: str; version: str; artifact_uri: str = ""; lifecycle: str = "candidate"; evaluation: dict = {}
class PipelineIn(BaseModel): name: str; definition: dict = {}; enabled: bool = False

def plan_hcl(w: Workload, provider: str):
    r = recommendation(w)
    return f'''# AstraDeploy generated plan-only configuration\n# Provider: {provider}\n# This configuration is not applied automatically.\nresource "container_service" "{w.name.replace("-", "_")}" {{\n  cpu = {r["recommended_cpu"]}\n  memory_gb = {r["recommended_memory_gb"]}\n  replicas = {r["replicas"]}\n  region = "{w.region}"\n}}'''
def workspace_items(workspace_id: int, user: User, session: Session):
    member_workspace(workspace_id, user, session)

def audit(session: Session, workspace_id: int, user_id: int, action: str):
    session.add(AuditEvent(workspace_id=workspace_id, user_id=user_id, action=action))

@app.get("/api/workspaces/{workspace_id}/providers")
def provider_status(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session)
    rows = list(session.scalars(select(ProviderConnection).where(ProviderConnection.workspace_id == workspace_id)).all())
    by_name = {r.provider: r for r in rows}
    return [{"provider": p, "status": by_name[p].status if p in by_name else "disconnected", "region": by_name[p].region if p in by_name else "unspecified", "account_id": by_name[p].account_id if p in by_name else ""} for p in ["aws", "azure", "gcp"]]
@app.post("/api/workspaces/{workspace_id}/providers", status_code=201)
def connect_provider(workspace_id: int, data: ProviderIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session)
    if data.provider not in {"aws", "azure", "gcp"}: raise HTTPException(400, "Provider must be aws, azure, or gcp")
    row = session.scalar(select(ProviderConnection).where(ProviderConnection.workspace_id == workspace_id, ProviderConnection.provider == data.provider))
    if not row: row = ProviderConnection(workspace_id=workspace_id, provider=data.provider); session.add(row)
    row.status = "configured_pending_validation"; row.region = data.region; row.account_id = data.account_id
    audit(session, workspace_id, user.id, f"provider.{data.provider}.configured"); session.commit()
    return {"provider": data.provider, "status": row.status, "message": "Credentials are metadata-only until a secure secret integration is configured."}
@app.get("/api/workspaces/{workspace_id}/provisioning-plans")
def list_plans(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"workload_id":x.workload_id,"provider":x.provider,"status":x.status,"cost_note":x.cost_note,"terraform_config":x.terraform_config} for x in session.scalars(select(ProvisioningPlan).where(ProvisioningPlan.workspace_id == workspace_id).order_by(ProvisioningPlan.id.desc())).all()]
@app.post("/api/workspaces/{workspace_id}/workloads/{workload_id}/provisioning-plans", status_code=201)
def create_plan(workspace_id: int, workload_id: int, provider: str = "none", user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); w = session.scalar(select(Workload).where(Workload.id == workload_id, Workload.workspace_id == workspace_id))
    if not w: raise HTTPException(404, "Workload not found")
    p = ProvisioningPlan(workspace_id=workspace_id, workload_id=workload_id, provider=provider, terraform_config=plan_hcl(w, provider)); session.add(p); audit(session, workspace_id, user.id, "provisioning.plan.created"); session.commit(); session.refresh(p)
    return {"id":p.id,"status":"plan_only","provider":provider,"terraform_config":p.terraform_config,"cost_note":p.cost_note,"apply_allowed":False}
@app.get("/api/workspaces/{workspace_id}/deployments")
def list_deployments(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"workload_id":x.workload_id,"provider":x.provider,"status":x.status,"external_id":x.external_id} for x in session.scalars(select(Deployment).where(Deployment.workspace_id == workspace_id).order_by(Deployment.id.desc())).all()]
@app.get("/api/workspaces/{workspace_id}/monitoring")
def monitoring(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); rows = session.scalars(select(MetricObservation).where(MetricObservation.workspace_id == workspace_id).order_by(MetricObservation.observed_at.desc()).limit(100)).all()
    return {"connected": bool(rows), "message": "No telemetry source connected" if not rows else "User/source observations", "observations":[{"metric":x.metric,"value":x.value,"source":x.source,"observed_at":x.observed_at} for x in rows]}
@app.post("/api/workspaces/{workspace_id}/metrics", status_code=201)
def add_metric(workspace_id: int, data: MetricIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=MetricObservation(workspace_id=workspace_id, **data.model_dump()); session.add(x); audit(session, workspace_id, user.id, "monitoring.observation.created"); session.commit(); return {"id":x.id,"status":"recorded"}
@app.get("/api/workspaces/{workspace_id}/cost-observations")
def cost_observations(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"amount":x.amount,"currency":x.currency,"source":x.source,"observed_at":x.observed_at} for x in session.scalars(select(CostObservation).where(CostObservation.workspace_id == workspace_id).order_by(CostObservation.observed_at.desc())).all()]
@app.post("/api/workspaces/{workspace_id}/cost-observations", status_code=201)
def add_cost(workspace_id: int, data: CostIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=CostObservation(workspace_id=workspace_id, **data.model_dump()); session.add(x); audit(session, workspace_id, user.id, "cost.observation.created"); session.commit(); return {"id":x.id,"status":"recorded"}
@app.get("/api/workspaces/{workspace_id}/alerts")
def alerts(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"severity":x.severity,"title":x.title,"status":x.status,"details":x.details,"created_at":x.created_at} for x in session.scalars(select(Alert).where(Alert.workspace_id == workspace_id).order_by(Alert.id.desc())).all()]
@app.post("/api/workspaces/{workspace_id}/alerts", status_code=201)
def add_alert(workspace_id: int, data: AlertIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=Alert(workspace_id=workspace_id, **data.model_dump()); session.add(x); audit(session, workspace_id, user.id, "alert.created"); session.commit(); session.refresh(x); return {"id":x.id,"severity":x.severity,"title":x.title,"status":x.status}
@app.get("/api/workspaces/{workspace_id}/audit-logs")
def audit_logs(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"action":x.action,"user_id":x.user_id,"created_at":x.created_at} for x in session.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(AuditEvent.id.desc()).limit(200)).all()]
@app.post("/api/workspaces/{workspace_id}/experiments", status_code=201)
def create_experiment(workspace_id: int, data: ExperimentIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=Experiment(workspace_id=workspace_id,name=data.name,dataset_ref=data.dataset_ref,hyperparameters=str(data.hyperparameters)); session.add(x); audit(session, workspace_id, user.id, "ml.experiment.created"); session.commit(); session.refresh(x); return {"id":x.id,"name":x.name,"status":x.status,"dataset_ref":x.dataset_ref,"hyperparameters":data.hyperparameters}
@app.get("/api/workspaces/{workspace_id}/experiments")
def experiments(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"name":x.name,"status":x.status,"dataset_ref":x.dataset_ref,"metrics":x.metrics} for x in session.scalars(select(Experiment).where(Experiment.workspace_id == workspace_id)).all()]
@app.post("/api/workspaces/{workspace_id}/models", status_code=201)
def create_model(workspace_id: int, data: ModelIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=ModelVersion(workspace_id=workspace_id,name=data.name,version=data.version,artifact_uri=data.artifact_uri,lifecycle=data.lifecycle,evaluation=str(data.evaluation)); session.add(x); audit(session, workspace_id, user.id, "ml.model_version.created"); session.commit(); session.refresh(x); return {"id":x.id,"name":x.name,"version":x.version,"lifecycle":x.lifecycle,"artifact_uri":x.artifact_uri}
@app.get("/api/workspaces/{workspace_id}/models")
def models(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"name":x.name,"version":x.version,"lifecycle":x.lifecycle,"artifact_uri":x.artifact_uri} for x in session.scalars(select(ModelVersion).where(ModelVersion.workspace_id == workspace_id)).all()]
@app.post("/api/workspaces/{workspace_id}/pipelines", status_code=201)
def create_pipeline(workspace_id: int, data: PipelineIn, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); x=Pipeline(workspace_id=workspace_id,name=data.name,definition=str(data.definition),enabled=data.enabled); session.add(x); audit(session, workspace_id, user.id, "ml.pipeline.created"); session.commit(); session.refresh(x); return {"id":x.id,"name":x.name,"enabled":x.enabled,"definition":data.definition}
@app.get("/api/workspaces/{workspace_id}/pipelines")
def pipelines(workspace_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    workspace_items(workspace_id, user, session); return [{"id":x.id,"name":x.name,"enabled":x.enabled,"definition":x.definition} for x in session.scalars(select(Pipeline).where(Pipeline.workspace_id == workspace_id)).all()]
