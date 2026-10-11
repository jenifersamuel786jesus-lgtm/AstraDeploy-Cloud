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
