from fastapi import Body, FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func, or_
from typing import Any, Dict, List, Optional
import datetime
import json
import os, shutil
from pathlib import Path
from uuid import uuid4

import database, models, schemas, auth, reporting, framework_library_db, policy_assessment, grcxpert_assistance

models.Base.metadata.create_all(bind=database.engine)
framework_library_db.init_framework_library_db()


# ═══════════════════════════════════════════════════════════════════════════════
# CHANGE 1 — Replaced @app.on_event("startup") with lifespan context manager
#
# OLD CODE:
#   app = FastAPI(title="Noryx API")
#   @app.on_event("startup")
#   def seed_data():
#       db = database.SessionLocal()
#       ...
#
# WHY THE NEW ONE IS BETTER:
#   @app.on_event("startup") is officially deprecated since FastAPI 0.93.
#   The lifespan approach is the modern standard: it handles both startup
#   AND shutdown logic in one place using a clean async context manager,
#   and future-proofs the code against upcoming FastAPI versions that will
#   remove the old decorator entirely.
# ═══════════════════════════════════════════════════════════════════════════════

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_data()
    yield

app = FastAPI(title="Noryx API", lifespan=lifespan)
app.include_router(grcxpert_assistance.router)

def _seed_data():
    db = database.SessionLocal()
    try:
        dept = db.query(models.Department).filter(models.Department.name == "IT Security").first()
        if not dept:
            dept = models.Department(name="IT Security", description="Default IT Sec Dept")
            db.add(dept)
            db.commit()
            db.refresh(dept)

        admin = db.query(models.User).filter(models.User.username == "admin").first()
        if not admin:
            db.add(models.User(
                username="admin",
                password_hash=auth.get_password_hash("admin123"),
                role="admin"
            ))

        employee = db.query(models.User).filter(models.User.username == "employee").first()
        if not employee:
            db.add(models.User(
                username="employee",
                password_hash=auth.get_password_hash("emp123"),
                role="employee",
                department_id=dept.id
            ))
        db.commit()

        if db.query(models.Control).count() == 0:
            _seed_nca_controls(db)
    finally:
        db.close()


def _seed_nca_controls(db):
    search_paths = [
        Path(__file__).parent / "nca_controls.json",
        Path(__file__).parent.parent / "nca_controls.json",
        Path(__file__).parent.parent.parent / "nca_controls.json",
    ]
    nca_path = next((p for p in search_paths if p.exists()), None)
    if nca_path is None:
        return

    try:
        items = json.loads(nca_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(items, list):
        return

    departments_by_name = _ensure_mapping_departments(db)
    due_date = datetime.datetime(2025, 12, 31, 23, 59, 59)

    for item in items:
        if not isinstance(item, dict):
            continue
        name        = (item.get("name")        or "").strip()
        description = (item.get("description") or "").strip()
        criteria    = (item.get("criteria")    or "").strip()
        if not name:
            continue

        dept_id, dept_name, _ = _classify_control_to_department(
            name, description, criteria, departments_by_name,
        )

        ctrl = models.Control(
            name=name,
            description=description,
            criteria=criteria,
            category=dept_name,
            department_id=dept_id,
        )
        db.add(ctrl)
        db.flush()

        db.add(models.Task(
            title=f"Implement & evidence control {name}",
            department_id=dept_id,
            control_id=ctrl.id,
            due_date=due_date,
            status="Pending",
        ))

    db.commit()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_framework_db():
    db = framework_library_db.SessionLocal()
    try:
        yield db
    finally:
        db.close()

os.makedirs("uploads", exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# DEPARTMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/departments/", response_model=schemas.Department)
def create_department(dept: schemas.DepartmentCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Department).filter(models.Department.name == dept.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists")
    db_dept = models.Department(**dept.dict())
    db.add(db_dept)
    db.commit()
    db.refresh(db_dept)
    return db_dept

@app.get("/departments/", response_model=List[schemas.Department])
def list_departments(db: Session = Depends(get_db)):
    return db.query(models.Department).all()

@app.delete("/departments/{dept_id}")
def delete_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(models.Department).filter(models.Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(dept)
    db.commit()
    return {"message": "Deleted"}

@app.get("/departments/{dept_id}/controls", response_model=List[schemas.Control])
def get_dept_controls(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Control).filter(models.Control.department_id == dept_id).all()

@app.get("/departments/{dept_id}/employees", response_model=List[schemas.Employee])
def get_dept_employees(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Employee).filter(models.Employee.department_id == dept_id).all()


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/employees/", response_model=schemas.Employee)
def create_employee(emp: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    db_emp = models.Employee(**emp.dict())
    db.add(db_emp)
    db.commit()
    db.refresh(db_emp)
    return db_emp

@app.get("/employees/", response_model=List[schemas.Employee])
def list_employees(db: Session = Depends(get_db)):
    return db.query(models.Employee).all()


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/controls/", response_model=schemas.Control)
def create_control(control: schemas.ControlCreate, db: Session = Depends(get_db)):
    db_ctrl = models.Control(**control.dict())
    db.add(db_ctrl)
    db.commit()
    db.refresh(db_ctrl)
    return db_ctrl

@app.get("/controls/", response_model=List[schemas.Control])
def list_controls(db: Session = Depends(get_db)):
    return db.query(models.Control).all()

@app.patch("/controls/{control_id}", response_model=schemas.Control)
def update_control(control_id: int, update: schemas.ControlUpdate, db: Session = Depends(get_db)):
    ctrl = db.query(models.Control).filter(models.Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")
    if update.department_id is not None:
        ctrl.department_id = update.department_id
    if update.category is not None:
        ctrl.category = update.category
    db.commit()
    db.refresh(ctrl)
    return ctrl


# ═══════════════════════════════════════════════════════════════════════════════
# DYNAMIC NCA UPLOAD + AUTO DEPARTMENT MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

DEPT_KEYWORD_MAP: List[tuple] = [
    ("Network Security", "Firewalls, segmentation, VPN, perimeter and traffic controls", [
        "firewall","network","dmz","vpn","router","switch","port","traffic","segment",
        "inbound","outbound","packet","proxy","waf","ids","ips","intrusion","perimeter",
        "subnet","vlan","nat","dns","dhcp","bandwidth","wireless","wi-fi","wifi",
    ]),
    ("Identity & Access", "Authentication, MFA, privileged access, identity governance", [
        "mfa","password","authentication","authorization","access","privilege","account",
        "identity","iam","login","credential","permission","active directory","ldap",
        "sso","oauth","pam","least privilege","group policy",
    ]),
    ("Endpoint Protection", "Antivirus, EDR, patching, endpoint hardening", [
        "antivirus","malware","endpoint","device","patch","edr","definition","scan",
        "quarantine","real-time","hotfix","cve","remediat","mobile device","byod",
    ]),
    ("Data Security", "Encryption, classification, DLP, backup and recovery", [
        "encrypt","backup","database","classif","dlp","bitlocker","tls","ssl","storage",
        "transit","at rest","key management","certificate","sensitive","confidential",
        "retention","archive","restore","recovery","rpo","rto","data leakage",
    ]),
    ("Incident Response", "Detection, SIEM, forensics, breach handling", [
        "incident","alert","log","siem","monitor","detect","forensic","investigation",
        "threat","attack","breach","correlation","triage","ioc","playbook","escalat",
        "contain","eradicate","soc",
    ]),
    ("Compliance & Governance", "Policy, audit, governance, regulatory compliance", [
        "audit","compliance","policy","procedure","governance","regulation","standard",
        "framework","nca","ecc","gdpr","iso","nist","review","exception","waiver",
        "report","strategy","steering committee","authorized official","documented","approved",
    ]),
    ("Risk Management", "Risk assessment, mitigation strategy, risk register", [
        "risk","threat assessment","likelihood","impact","mitigation","tolerance",
        "appetite","risk register",
    ]),
    ("Human Resources", "Personnel security, training, awareness, HR processes", [
        "personnel","training","awareness","employee","staff","onboarding","termination",
        "hire","leaver","background check","screening","contract","disciplinar",
        "saudi cybersecurity","positions shall be filled","human resources","full-time",
    ]),
    ("IT Operations", "Infrastructure, configuration, change and asset management", [
        "server","infrastructure","configuration","change management","asset",
        "inventory","operating system","datacenter","virtuali","container","docker",
        "kubernetes","ci/cd","devops","deployment","capacity",
    ]),
    ("Physical Security", "Facility access, CCTV, hardware and media security", [
        "physical","facility","cctv","camera","badge","door","access card","lock",
        "guard","visitor","building","server room","clean desk","shredding","disposal",
        "media","usb","removable",
    ]),
    ("Vendor & Third-Party Management", "Third-party / supplier risk and contracts", [
        "third party","third-party","vendor","supplier","outsourc","sla","contract management",
    ]),
    ("Cloud & Hosting", "Cloud workloads, SaaS/IaaS/PaaS, hosting", [
        "cloud","saas","iaas","paas","aws","azure","gcp","tenant","hosting",
    ]),
    ("Business Continuity", "BCP, disaster recovery, resilience", [
        "business continuity","bcp","disaster recovery","drp","resilien","contingency",
    ]),
    ("Application Security", "Secure SDLC, code review, app pen-testing", [
        "application security","secure coding","sdlc","code review","penetration test",
        "owasp","api security","web application",
    ]),
]

DEFAULT_FALLBACK_DEPT = "Compliance & Governance"

import re as _re
_NCA_PATTERN = _re.compile(r"^(\d+-\d+)-\d+$")
NCA_FAMILY_TO_DEPT: Dict[str, str] = {
    "1-1":  "Compliance & Governance",
    "1-2":  "Compliance & Governance",
    "1-3":  "Compliance & Governance",
    "1-4":  "Compliance & Governance",
    "1-5":  "Risk Management",
    "1-6":  "IT Operations",
    "1-7":  "Compliance & Governance",
    "1-8":  "Compliance & Governance",
    "1-9":  "Human Resources",
    "1-10": "Human Resources",
    "2-1":  "IT Operations",
    "2-2":  "Identity & Access",
    "2-3":  "Endpoint Protection",
    "2-4":  "Network Security",
    "2-5":  "Network Security",
    "2-6":  "Endpoint Protection",
    "2-7":  "Data Security",
    "2-8":  "Data Security",
    "2-9":  "Data Security",
    "2-10": "Endpoint Protection",
    "2-11": "Application Security",
    "2-12": "Incident Response",
    "2-13": "Incident Response",
    "2-14": "Physical Security",
    "2-15": "Application Security",
    "3-1":  "Business Continuity",
    "4-1":  "Vendor & Third-Party Management",
    "4-2":  "Cloud & Hosting",
}


def _nca_family_department(name: str) -> Optional[str]:
    if not name:
        return None
    m = _NCA_PATTERN.match(name.strip())
    if not m:
        return None
    return NCA_FAMILY_TO_DEPT.get(m.group(1))


def _classify_control_to_department(
    name: str,
    description: str,
    criteria: str,
    departments_by_name: Dict[str, models.Department],
) -> tuple:
    nca_dept = _nca_family_department(name)
    if nca_dept and nca_dept in departments_by_name:
        dept = departments_by_name[nca_dept]
        return dept.id, nca_dept, 999

    text_blob = f"{name or ''} {description or ''} {criteria or ''}".lower()
    best_name, best_score = None, 0
    for dept_name, _desc, kws in DEPT_KEYWORD_MAP:
        score = sum(1 for kw in kws if kw in text_blob)
        if score > best_score:
            best_score, best_name = score, dept_name

    if best_name is None or best_score == 0:
        best_name = DEFAULT_FALLBACK_DEPT

    dept = departments_by_name.get(best_name)
    return (dept.id if dept else None), best_name, best_score


def _ensure_mapping_departments(db: Session) -> Dict[str, models.Department]:
    for dept_name, desc, _kws in DEPT_KEYWORD_MAP:
        existing = (
            db.query(models.Department)
            .filter(models.Department.name == dept_name)
            .first()
        )
        if not existing:
            db.add(models.Department(name=dept_name, description=desc))
    db.commit()
    return {d.name: d for d in db.query(models.Department).all()}


@app.post("/admin/controls/clear")
def admin_clear_all_controls(db: Session = Depends(get_db)):
    n_risks    = db.query(models.Risk).delete(synchronize_session=False)
    n_evidence = db.query(models.Evidence).delete(synchronize_session=False)
    n_tasks    = db.query(models.Task).delete(synchronize_session=False)
    n_controls = db.query(models.Control).delete(synchronize_session=False)
    db.commit()
    return {
        "controls_deleted": n_controls,
        "tasks_deleted":    n_tasks,
        "evidence_deleted": n_evidence,
        "risks_deleted":    n_risks,
    }


@app.post("/admin/controls/upload-nca")
async def admin_upload_nca_controls(
    file: UploadFile = File(...),
    deadline: str = Form(...),
    replace_existing: bool = Form(True),
    db: Session = Depends(get_db),
):
    try:
        raw = await file.read()
        items = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="JSON root must be an array of controls.")

    try:
        if len(deadline) <= 10:
            due_date = datetime.datetime.fromisoformat(deadline + "T23:59:59")
        else:
            due_date = datetime.datetime.fromisoformat(deadline.replace("Z", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="deadline must be ISO 8601 (YYYY-MM-DD or full datetime).")

    if replace_existing:
        db.query(models.Risk).delete(synchronize_session=False)
        db.query(models.Evidence).delete(synchronize_session=False)
        db.query(models.Task).delete(synchronize_session=False)
        db.query(models.Control).delete(synchronize_session=False)
        db.commit()

    departments_by_name = _ensure_mapping_departments(db)

    controls_created     = 0
    controls_skipped     = 0
    tasks_created        = 0
    department_assignments: Dict[str, int] = {}
    sample_assignments: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        name        = (item.get("name")        or "").strip()
        description = (item.get("description") or "").strip()
        criteria    = (item.get("criteria")    or "").strip()
        if not name:
            continue

        if not replace_existing:
            existing = db.query(models.Control).filter(models.Control.name == name).first()
            if existing:
                controls_skipped += 1
                continue

        dept_id, dept_name, score = _classify_control_to_department(
            name, description, criteria, departments_by_name,
        )

        ctrl = models.Control(
            name=name,
            description=description,
            criteria=criteria,
            category=dept_name,
            department_id=dept_id,
        )
        db.add(ctrl)
        db.flush()

        task = models.Task(
            title=f"Implement & evidence control {name}",
            department_id=dept_id,
            control_id=ctrl.id,
            due_date=due_date,
            status="Pending",
        )
        db.add(task)

        controls_created += 1
        tasks_created    += 1
        department_assignments[dept_name] = department_assignments.get(dept_name, 0) + 1
        if len(sample_assignments) < 8:
            sample_assignments.append({
                "control": name,
                "department": dept_name,
                "match_score": score,
            })

    db.commit()

    return {
        "controls_created":          controls_created,
        "controls_skipped_existing": controls_skipped,
        "tasks_created":             tasks_created,
        "deadline":                  due_date.isoformat(),
        "replaced_existing":         replace_existing,
        "departments": [
            {"name": k, "controls_assigned": v}
            for k, v in sorted(department_assignments.items(), key=lambda x: -x[1])
        ],
        "sample_assignments": sample_assignments,
    }


@app.get("/tasks/summary")
def tasks_summary(db: Session = Depends(get_db)):
    now = datetime.datetime.utcnow()
    rows = []
    for d in db.query(models.Department).order_by(models.Department.name).all():
        total = db.query(models.Task).filter(models.Task.department_id == d.id).count()
        if total == 0:
            continue
        completed   = db.query(models.Task).filter(models.Task.department_id == d.id, models.Task.status == "Completed").count()
        in_progress = db.query(models.Task).filter(models.Task.department_id == d.id, models.Task.status == "In Progress").count()
        overdue     = db.query(models.Task).filter(
            models.Task.department_id == d.id,
            models.Task.status != "Completed",
            models.Task.due_date < now,
        ).count()
        rows.append({
            "department_id":   d.id,
            "department_name": d.name,
            "total":           total,
            "completed":       completed,
            "in_progress":     in_progress,
            "pending":         total - completed - in_progress,
            "overdue":         overdue,
            "progress_pct":    round((completed / total) * 100, 1) if total else 0.0,
        })
    rows.sort(key=lambda r: -r["total"])

    overall_total     = sum(r["total"] for r in rows)
    overall_completed = sum(r["completed"] for r in rows)
    return {
        "overall": {
            "total":        overall_total,
            "completed":    overall_completed,
            "progress_pct": round((overall_completed / overall_total) * 100, 1) if overall_total else 0.0,
        },
        "departments": rows,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ISOLATED FRAMEWORK LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════

def _framework_control_dict(control):
    return {
        "id": control.id,
        "framework_key": control.framework_key,
        "framework_name": control.framework_name,
        "version": control.version,
        "control_id": control.control_id,
        "title": control.title,
        "domain": control.domain,
        "category": control.category,
        "control_text": control.control_text,
        "source_file": control.source_file,
        "page": control.page,
    }


def _framework_mapping_dict(mapping):
    return {
        "id": mapping.id,
        "source_framework": mapping.source_framework,
        "source_control_id": mapping.source_control_id,
        "source_control_title": mapping.source_control_title,
        "target_framework": mapping.target_framework,
        "target_control_id": mapping.target_control_id,
        "scf_control_id": mapping.scf_control_id,
        "scf_control_title": mapping.scf_control_title,
        "relationship_type": mapping.relationship_type,
        "match_score": mapping.match_score,
        "notes": mapping.notes,
    }


def _policy_document_dict(document):
    return {
        "id": document.id,
        "company_name": document.company_name,
        "document_type": document.document_type,
        "original_filename": document.original_filename,
        "stored_filename": document.stored_filename,
        "stored_path": document.stored_path,
        "content_type": document.content_type,
        "file_size": document.file_size,
        "notes": document.notes,
        "uploaded_by": document.uploaded_by,
        "uploaded_at": document.uploaded_at,
    }


@app.get("/framework-library/summary")
def framework_library_summary(db: Session = Depends(get_framework_db)):
    control_counts = (
        db.query(
            framework_library_db.FrameworkControl.framework_key,
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.version,
            func.count(framework_library_db.FrameworkControl.id),
        )
        .group_by(
            framework_library_db.FrameworkControl.framework_key,
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.version,
        )
        .order_by(framework_library_db.FrameworkControl.framework_name)
        .all()
    )
    mapping_counts = (
        db.query(
            framework_library_db.FrameworkMapping.target_framework,
            func.count(framework_library_db.FrameworkMapping.id),
        )
        .group_by(framework_library_db.FrameworkMapping.target_framework)
        .order_by(framework_library_db.FrameworkMapping.target_framework)
        .all()
    )
    return {
        "source_count": db.query(framework_library_db.FrameworkSource).count(),
        "total_controls": db.query(framework_library_db.FrameworkControl).count(),
        "total_mappings": db.query(framework_library_db.FrameworkMapping).count(),
        "database": str(framework_library_db.FRAMEWORK_DB_PATH),
        "framework_counts": [
            {
                "framework_key": key,
                "framework_name": name,
                "version": version,
                "controls": count,
            }
            for key, name, version, count in control_counts
        ],
        "mapping_counts": [
            {"target_framework": target, "mappings": count}
            for target, count in mapping_counts
        ],
    }


@app.get("/framework-library/sources")
def framework_library_sources(db: Session = Depends(get_framework_db)):
    sources = (
        db.query(framework_library_db.FrameworkSource)
        .order_by(framework_library_db.FrameworkSource.framework_name)
        .all()
    )
    return [
        {
            "id": src.id,
            "framework_key": src.framework_key,
            "framework_name": src.framework_name,
            "version": src.version,
            "owner": src.owner,
            "raw_format": src.raw_format,
            "source_filename": src.source_filename,
            "stored_path": src.stored_path,
            "imported_at": src.imported_at,
            "control_count": src.control_count,
            "mapping_count": src.mapping_count,
        }
        for src in sources
    ]


@app.get("/framework-library/controls")
def framework_library_controls(
    framework: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_framework_db),
):
    limit = min(max(limit, 1), 300)
    offset = max(offset, 0)
    query = db.query(framework_library_db.FrameworkControl)
    if framework:
        query = query.filter(
            or_(
                framework_library_db.FrameworkControl.framework_key == framework,
                framework_library_db.FrameworkControl.framework_name.ilike(f"%{framework}%"),
            )
        )
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkControl.control_id.ilike(like),
                framework_library_db.FrameworkControl.title.ilike(like),
                framework_library_db.FrameworkControl.domain.ilike(like),
                framework_library_db.FrameworkControl.control_text.ilike(like),
            )
        )
    total = query.count()
    items = (
        query.order_by(
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.control_id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_framework_control_dict(item) for item in items],
    }


@app.get("/framework-library/mappings")
def framework_library_mappings(
    framework: Optional[str] = None,
    target_framework: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_framework_db),
):
    limit = min(max(limit, 1), 300)
    offset = max(offset, 0)
    query = db.query(framework_library_db.FrameworkMapping)
    if framework:
        like = f"%{framework}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkMapping.source_framework.ilike(like),
                framework_library_db.FrameworkMapping.target_framework.ilike(like),
            )
        )
    if target_framework:
        query = query.filter(framework_library_db.FrameworkMapping.target_framework.ilike(f"%{target_framework}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkMapping.source_control_id.ilike(like),
                framework_library_db.FrameworkMapping.source_control_title.ilike(like),
                framework_library_db.FrameworkMapping.target_control_id.ilike(like),
                framework_library_db.FrameworkMapping.scf_control_id.ilike(like),
                framework_library_db.FrameworkMapping.scf_control_title.ilike(like),
            )
        )
    total = query.count()
    items = (
        query.order_by(
            framework_library_db.FrameworkMapping.target_framework,
            framework_library_db.FrameworkMapping.target_control_id,
            framework_library_db.FrameworkMapping.scf_control_id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_framework_mapping_dict(item) for item in items],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COMPANY POLICY DOCUMENTS (ISOLATED UPLOADS)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/policy-documents/upload")
def upload_policy_document(
    company_name: str = Form(...),
    document_type: str = Form("Policy Pack"),
    notes: Optional[str] = Form(""),
    uploaded_by: Optional[str] = Form("Admin"),
    file: UploadFile = File(...),
    db: Session = Depends(get_framework_db),
):
    if not company_name.strip():
        raise HTTPException(status_code=400, detail="company_name is required")

    original = Path(file.filename or "policy-document").name
    suffix = Path(original).suffix.lower()
    allowed = {".pdf", ".docx", ".doc", ".txt"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, DOC, and TXT policy files are supported")

    stored_filename = f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:10]}{suffix}"
    stored_path = framework_library_db.POLICY_UPLOAD_DIR / stored_filename

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = framework_library_db.PolicyDocument(
        company_name=company_name.strip(),
        document_type=(document_type or "Policy Pack").strip(),
        original_filename=original,
        stored_filename=stored_filename,
        stored_path=str(stored_path.relative_to(framework_library_db.PROJECT_ROOT)),
        content_type=file.content_type or "",
        file_size=stored_path.stat().st_size,
        notes=(notes or "").strip(),
        uploaded_by=(uploaded_by or "Admin").strip(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return _policy_document_dict(document)


@app.get("/policy-documents")
def list_policy_documents(
    company_name: Optional[str] = None,
    db: Session = Depends(get_framework_db),
):
    query = db.query(framework_library_db.PolicyDocument)
    if company_name:
        query = query.filter(framework_library_db.PolicyDocument.company_name.ilike(f"%{company_name}%"))
    documents = query.order_by(framework_library_db.PolicyDocument.uploaded_at.desc()).all()
    return [_policy_document_dict(document) for document in documents]


@app.get("/policy-documents/assessment-frameworks")
def policy_assessment_frameworks(db: Session = Depends(get_framework_db)):
    return {
        "items": policy_assessment.get_assessable_frameworks(db),
        "default_selection": "all",
        "engine": policy_assessment.ENGINE_NAME,
        "engines": policy_assessment.get_assessment_engines(),
    }


@app.post("/policy-documents/{document_id}/assess")
def assess_policy_document(
    document_id: int,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    db: Session = Depends(get_framework_db),
):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    selected = (payload or {}).get("frameworks") or ["all"]
    engine = (payload or {}).get("engine") or policy_assessment.ENGINE_NAME
    try:
        return policy_assessment.assess_policy_document(db, document, selected, engine=engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/policy-documents/{document_id}/assessment-report")
def get_policy_assessment_report(
    document_id: int,
    frameworks: Optional[str] = None,
    engine: Optional[str] = None,
    db: Session = Depends(get_framework_db),
):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    selected = [item.strip() for item in frameworks.split(",")] if frameworks else ["all"]
    try:
        assessment = policy_assessment.assess_policy_document(db, document, selected, engine=engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    report_name = f"policy-assessment-{document.id}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}.pdf"
    report_path = framework_library_db.POLICY_REPORT_DIR / report_name
    policy_assessment.build_assessment_pdf(assessment, report_path)
    download_name = f"{Path(document.original_filename).stem}-assessment-report.pdf"
    return FileResponse(report_path, media_type="application/pdf", filename=download_name)


@app.get("/policy-documents/{document_id}/file")
def get_policy_document_file(document_id: int, db: Session = Depends(get_framework_db)):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    path = framework_library_db.PROJECT_ROOT / document.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Policy document file not found")
    return FileResponse(path, media_type=document.content_type or None, filename=document.original_filename)


@app.delete("/policy-documents/{document_id}")
def delete_policy_document(document_id: int, db: Session = Depends(get_framework_db)):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    path = framework_library_db.PROJECT_ROOT / document.stored_path
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    db.delete(document)
    db.commit()
    return {"message": "Policy document deleted", "document_id": document_id}


# ═══════════════════════════════════════════════════════════════════════════════
# EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/evidence/upload/")
def upload_evidence(
    control_id:    int            = Form(...),
    department_id: Optional[int]  = Form(None),
    employee_name: Optional[str]  = Form("Unknown"),
    file:          UploadFile     = File(...),
    db:            Session        = Depends(get_db),
):
    import ai_engine

    ctrl = db.query(models.Control).filter(models.Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    file_location = f"uploads/{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    full_context = f"{ctrl.criteria or ''} {ctrl.description or ''}".strip()
    status, extracted_text, confidence = ai_engine.validate_evidence(file_location, full_context)

    review_state = "auto" if status.lower() == "pass" else "pending_manager"

    db_ev = models.Evidence(
        control_id=control_id,
        department_id=department_id,
        employee_name=employee_name,
        file_path=file_location,
        status=status,
        extracted_text=extracted_text,
        ai_confidence=confidence,
        ai_status=status,
        review_state=review_state,
    )
    db.add(db_ev)
    db.commit()
    db.refresh(db_ev)

    if status.lower() == "fail":
        db_risk = models.Risk(
            title=f"AI Validation Failure: Control #{control_id}",
            description=f"Automated risk created due to invalid evidence upload by {employee_name}.",
            control_id=control_id,
            evidence_id=db_ev.id,
            impact="High",
            likelihood="Medium",
            status="Open"
        )
        db.add(db_risk)
        db.commit()

    return {
        "message": "File uploaded and validated",
        "evidence_id": db_ev.id,
        "status": status,
        "confidence": confidence,
        "extracted_text": extracted_text,
        "review_state": review_state,
    }

@app.get("/evidence/", response_model=List[schemas.Evidence])
def list_evidence(db: Session = Depends(get_db)):
    return db.query(models.Evidence).order_by(models.Evidence.upload_time.desc()).all()

@app.post("/evidence/{evidence_id}/review")
def review_evidence(evidence_id: int, final_status: str = Form(...), db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    ev.status = final_status
    db.commit()
    if final_status.lower() in ["pass", "fail"]:
        dataset_dir = f"dataset/train/{final_status.lower()}"
        os.makedirs(dataset_dir, exist_ok=True)
        shutil.copy(ev.file_path, os.path.join(dataset_dir, os.path.basename(ev.file_path)))
    return {"message": f"Evidence marked as {final_status}"}


@app.get("/evidence/pending-review", response_model=List[schemas.Evidence])
def list_pending_review(db: Session = Depends(get_db)):
    return (
        db.query(models.Evidence)
          .filter(models.Evidence.review_state == "pending_manager")
          .order_by(models.Evidence.upload_time.desc())
          .all()
    )


@app.get("/evidence/{evidence_id}", response_model=schemas.Evidence)
def get_evidence(evidence_id: int, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return ev


@app.get("/evidence/{evidence_id}/file")
def get_evidence_file(evidence_id: int, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev or not ev.file_path or not os.path.exists(ev.file_path):
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return FileResponse(ev.file_path)


@app.delete("/evidence/{evidence_id}")
def delete_evidence(evidence_id: int, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")

    risks = db.query(models.Risk).filter(models.Risk.evidence_id == ev.id).all()
    for r in risks:
        db.delete(r)

    try:
        if ev.file_path and os.path.exists(ev.file_path):
            os.remove(ev.file_path)
    except OSError:
        pass

    db.delete(ev)
    db.commit()
    return {"message": "Evidence deleted", "evidence_id": evidence_id}


@app.post("/evidence/{evidence_id}/manager-approve", response_model=schemas.Evidence)
def manager_approve(evidence_id: int, payload: schemas.ManagerApprove, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not (payload.justification or "").strip():
        raise HTTPException(status_code=400, detail="Justification is required to override AI verdict")

    final = (payload.final_status or "pass").lower()
    if final not in ("pass", "fail"):
        raise HTTPException(status_code=400, detail="final_status must be 'pass' or 'fail'")

    ev.status                = final
    ev.review_state          = "approved"
    ev.manager_decision      = "approved"
    ev.manager_justification = payload.justification.strip()
    ev.reviewed_by           = payload.reviewer or "Manager"
    ev.reviewed_at           = datetime.datetime.utcnow()

    if final == "pass":
        risks = db.query(models.Risk).filter(models.Risk.evidence_id == ev.id).all()
        for r in risks:
            r.status = "Closed"
            r.mitigation_strategy = (r.mitigation_strategy or "") + \
                f"\n[Manager override {ev.reviewed_at.isoformat()}]: {ev.manager_justification}"

    db.commit()
    db.refresh(ev)
    return ev


@app.post("/evidence/{evidence_id}/manager-reject", response_model=schemas.Evidence)
def manager_reject(evidence_id: int, payload: schemas.ManagerSendBack, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not (payload.comment or "").strip():
        raise HTTPException(status_code=400, detail="A comment is required when sending evidence back")

    ev.review_state     = "sent_back"
    ev.manager_decision = "sent_back"
    ev.manager_comment  = payload.comment.strip()
    ev.reviewed_by      = payload.reviewer or "Manager"
    ev.reviewed_at      = datetime.datetime.utcnow()
    db.commit()
    db.refresh(ev)
    return ev


@app.get("/departments/{dept_id}/sent-back", response_model=List[schemas.Evidence])
def list_sent_back_for_department(dept_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.Evidence)
          .filter(models.Evidence.department_id == dept_id,
                  models.Evidence.review_state == "sent_back")
          .order_by(models.Evidence.reviewed_at.desc().nullslast())
          .all()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# CHANGE 2 — dashboard_stats now uses DB-level aggregation (func.count)
#            instead of loading every evidence row into Python memory.
#
# OLD CODE:
#   evidences = db.query(models.Evidence).all()   # loads ALL rows into RAM
#   total  = len(evidences)
#   passed = sum(1 for e in evidences if e.status and e.status.lower() == "pass")
#   failed = sum(1 for e in evidences if e.status and e.status.lower() == "fail")
#   review = sum(1 for e in evidences if e.status and e.status.lower() == "need_review")
#
# WHY THE NEW ONE IS BETTER:
#   The old code fetches every column of every evidence row into Python
#   just to count them. With thousands of records this wastes memory and
#   is slow. The new version pushes counting down to the database with
#   func.count(), which is much faster and uses virtually no app memory.
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    total  = db.query(func.count(models.Evidence.id)).scalar() or 0
    passed = db.query(func.count(models.Evidence.id)).filter(func.lower(models.Evidence.status) == "pass").scalar() or 0
    failed = db.query(func.count(models.Evidence.id)).filter(func.lower(models.Evidence.status) == "fail").scalar() or 0
    review = db.query(func.count(models.Evidence.id)).filter(func.lower(models.Evidence.status) == "need_review").scalar() or 0
    overall = round((passed / total * 100) if total > 0 else 0, 1)

    departments = db.query(models.Department).all()
    dept_stats = []
    for dept in departments:
        d_total  = db.query(func.count(models.Evidence.id)).filter(models.Evidence.department_id == dept.id).scalar() or 0
        d_pass   = db.query(func.count(models.Evidence.id)).filter(models.Evidence.department_id == dept.id, func.lower(models.Evidence.status) == "pass").scalar() or 0
        d_fail   = db.query(func.count(models.Evidence.id)).filter(models.Evidence.department_id == dept.id, func.lower(models.Evidence.status) == "fail").scalar() or 0
        d_review = db.query(func.count(models.Evidence.id)).filter(models.Evidence.department_id == dept.id, func.lower(models.Evidence.status) == "need_review").scalar() or 0
        dept_stats.append({
            "department": dept.name,
            "total": d_total,
            "passed": d_pass,
            "failed": d_fail,
            "review": d_review,
            "compliance_pct": round((d_pass / d_total * 100) if d_total > 0 else 0, 1),
        })

    controls = db.query(models.Control).all()
    fail_rows = (
        db.query(models.Evidence.control_id, func.count(models.Evidence.id).label("cnt"))
          .filter(func.lower(models.Evidence.status) == "fail")
          .group_by(models.Evidence.control_id)
          .order_by(func.count(models.Evidence.id).desc())
          .limit(5)
          .all()
    )
    ctrl_name_map = {c.id: c.name for c in controls}
    top_failing = [{"control": ctrl_name_map.get(cid, "Unknown"), "fails": cnt} for cid, cnt in fail_rows]

    return {
        "overall_compliance": overall,
        "total_evidence": total,
        "total_pass": passed,
        "total_fail": failed,
        "total_review": review,
        "department_stats": dept_stats,
        "top_failing_controls": top_failing,
    }


@app.get("/dashboard/threats")
def dashboard_threats(
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    import threat_predictor

    evidences   = db.query(models.Evidence).filter(
        models.Evidence.status.ilike("fail")
    ).all()
    controls    = db.query(models.Control).all()
    departments = db.query(models.Department).all()

    if department_id is not None:
        scoped_ctrl_ids = {c.id for c in controls if c.department_id == department_id}
        controls  = [c for c in controls if c.id in scoped_ctrl_ids]
        evidences = [e for e in evidences if e.control_id in scoped_ctrl_ids]

    fail_counts: dict[int, int] = {}
    for ev in evidences:
        fail_counts[ev.control_id] = fail_counts.get(ev.control_id, 0) + 1

    if not fail_counts:
        return {
            "threats": [],
            "severity_counts": {"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
            "total_failed_controls": 0,
            "most_at_risk_department": None,
        }

    ctrl_map = {c.id: c for c in controls}
    dept_map = {d.id: d for d in departments}

    dept_fail: dict[int, int] = {}
    for ev in evidences:
        if ev.department_id:
            dept_fail[ev.department_id] = dept_fail.get(ev.department_id, 0) + 1

    most_at_risk_dept = None
    if dept_fail and department_id is None:
        worst_id = max(dept_fail, key=dept_fail.get)
        most_at_risk_dept = dept_map.get(worst_id, {}).name if worst_id in dept_map else None

    seen: dict[str, dict] = {}

    for ctrl_id, fail_count in fail_counts.items():
        ctrl = ctrl_map.get(ctrl_id)
        if not ctrl:
            continue

        dept_name = dept_map.get(ctrl.department_id).name if ctrl.department_id in dept_map else "Unassigned"

        preds = threat_predictor.predict_threats(
            control_name=ctrl.name or "",
            control_description=ctrl.description or "",
            control_category=ctrl.category or "",
            top_n=4,
        )

        for pred in preds:
            tid = pred["technique_id"]
            entry = {
                **pred,
                "triggered_by": ctrl.name,
                "department":   dept_name,
                "fail_count":   fail_count,
            }
            if tid not in seen or pred["combined_score"] > seen[tid]["combined_score"]:
                seen[tid] = entry

    threat_list = sorted(seen.values(), key=lambda x: x["combined_score"], reverse=True)

    sev_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for t in threat_list:
        label = t.get("severity_label", "Low")
        if label in sev_counts:
            sev_counts[label] += 1

    return {
        "threats":                threat_list,
        "severity_counts":        sev_counts,
        "total_failed_controls":  len(fail_counts),
        "most_at_risk_department": most_at_risk_dept,
    }


@app.get("/dashboard/stats/{dept_id}")
def department_stats(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(models.Department).filter(models.Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    evidences = db.query(models.Evidence).filter(models.Evidence.department_id == dept_id).all()
    controls  = db.query(models.Control).filter(models.Control.department_id == dept_id).all()

    total   = len(evidences)
    passed  = sum(1 for e in evidences if e.status and e.status.lower() == "pass")
    failed  = sum(1 for e in evidences if e.status and e.status.lower() == "fail")
    review  = sum(1 for e in evidences if e.status and e.status.lower() == "need_review")
    overall = round((passed / total * 100) if total > 0 else 0, 1)

    fail_map = {}
    for e in evidences:
        if e.status and e.status.lower() == "fail":
            fail_map[e.control_id] = fail_map.get(e.control_id, 0) + 1
    top_failing = sorted(
        [{"control": next((c.name for c in controls if c.id == cid), "Unknown"),
          "fails": cnt} for cid, cnt in fail_map.items()],
        key=lambda x: x["fails"], reverse=True
    )[:5]

    return {
        "department": dept.name,
        "department_id": dept_id,
        "overall_compliance": overall,
        "total_evidence": total,
        "total_pass": passed,
        "total_fail": failed,
        "total_review": review,
        "total_controls": len(controls),
        "top_failing_controls": top_failing,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION & USERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        password_hash=hashed_password,
        role=user.role,
        department_id=user.department_id
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/auth/login", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})

    access_token_expires = auth.timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role, "username": user.username}

@app.get("/users/me", response_model=schemas.User)
def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


# ═══════════════════════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# CHANGE 3 — Replaced print() mock-email block with Python logging.
#
# OLD CODE:
#   print("\n" + "="*60)
#   print("📧 MOCK EMAIL ALERT TRIGGERED (FR3)")
#   print(f"To: technical-staff@{dept_name.lower().replace(' ', '')}.company.com")
#   print(f"Subject: New Compliance Task Assigned: TSK-{db_task.id}")
#   print("Body:")
#   print(f"A new task '{db_task.title}' has been assigned to your department.")
#   print(f"Due Date: {db_task.due_date}")
#   print("Please log in to the Noryx platform to submit your evidence.")
#   print("="*60 + "\n")
#
# WHY THE NEW ONE IS BETTER:
#   print() writes to stdout with no timestamp, no severity level, and no
#   module context. logging.info() automatically adds all of those, and
#   makes it trivial to redirect output to a file, a monitoring service,
#   or filter by level in production. It is the industry standard for
#   server-side event recording.
# ═══════════════════════════════════════════════════════════════════════════════

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

@app.post("/tasks/", response_model=schemas.Task)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    db_task = models.Task(**task.dict())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    dept = db.query(models.Department).filter(models.Department.id == db_task.department_id).first()
    dept_name = dept.name if dept else "Unknown"
    logger.info(
        "MOCK EMAIL | To: technical-staff@%s.company.com | Subject: New Task TSK-%d: '%s' | Due: %s",
        dept_name.lower().replace(" ", ""),
        db_task.id,
        db_task.title,
        db_task.due_date,
    )

    return db_task

@app.get("/tasks/", response_model=List[schemas.Task])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(models.Task).all()

@app.get("/departments/{dept_id}/tasks", response_model=List[schemas.Task])
def get_dept_tasks(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Task).filter(models.Task.department_id == dept_id).all()

@app.patch("/tasks/{task_id}", response_model=schemas.Task)
def update_task(task_id: int, status: str, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status
    db.commit()
    db.refresh(task)
    return task


# ═══════════════════════════════════════════════════════════════════════════════
# RISKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/risks/", response_model=schemas.Risk)
def create_risk(risk: schemas.RiskCreate, db: Session = Depends(get_db)):
    db_risk = models.Risk(**risk.dict())
    db.add(db_risk)
    db.commit()
    db.refresh(db_risk)
    return db_risk

@app.get("/risks/", response_model=List[schemas.Risk])
def list_risks(db: Session = Depends(get_db)):
    return db.query(models.Risk).all()

@app.patch("/risks/{risk_id}", response_model=schemas.Risk)
def update_risk(risk_id: int, mitigation_strategy: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    risk = db.query(models.Risk).filter(models.Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    if mitigation_strategy is not None:
        risk.mitigation_strategy = mitigation_strategy
    if status is not None:
        risk.status = status
    db.commit()
    db.refresh(risk)
    return risk


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

_FREQ_DAYS = {"monthly": 30, "quarterly": 90, "biannually": 180, "annually": 365}

def _next_due(last: datetime.datetime | None, frequency: str) -> datetime.datetime:
    days = _FREQ_DAYS.get(frequency, 90)
    base = last or datetime.datetime.utcnow()
    return base + datetime.timedelta(days=days)


@app.get("/testing-schedules/")
def list_testing_schedules(db: Session = Depends(get_db)):
    rows = db.query(models.TestingSchedule).all()
    result = []
    for r in rows:
        ctrl = db.query(models.Control).filter(models.Control.id == r.control_id).first()
        result.append({
            "id": r.id,
            "control_id": r.control_id,
            "control_name": ctrl.name if ctrl else None,
            "control_category": ctrl.category if ctrl else None,
            "frequency": r.frequency,
            "last_tested_at": r.last_tested_at.isoformat() if r.last_tested_at else None,
            "next_due_at": r.next_due_at.isoformat() if r.next_due_at else None,
            "owner": r.owner,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/testing-schedules/")
def create_testing_schedule(
    control_id: int = Body(...),
    frequency: str = Body("quarterly"),
    owner: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    existing = db.query(models.TestingSchedule).filter(models.TestingSchedule.control_id == control_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Schedule already exists for this control")
    next_due = _next_due(None, frequency)
    sched = models.TestingSchedule(
        control_id=control_id,
        frequency=frequency,
        owner=owner,
        notes=notes,
        next_due_at=next_due,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return {"id": sched.id, "next_due_at": sched.next_due_at.isoformat()}


@app.post("/testing-schedules/{sched_id}/mark-tested")
def mark_tested(sched_id: int, db: Session = Depends(get_db)):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    now = datetime.datetime.utcnow()
    sched.last_tested_at = now
    sched.next_due_at = _next_due(now, sched.frequency)
    db.commit()
    db.refresh(sched)
    return {"last_tested_at": sched.last_tested_at.isoformat(), "next_due_at": sched.next_due_at.isoformat()}


@app.patch("/testing-schedules/{sched_id}")
def update_testing_schedule(
    sched_id: int,
    frequency: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Not found")
    if frequency is not None:
        sched.frequency = frequency
        sched.next_due_at = _next_due(sched.last_tested_at, frequency)
    if owner is not None:
        sched.owner = owner
    if notes is not None:
        sched.notes = notes
    db.commit()
    return {"ok": True}


@app.delete("/testing-schedules/{sched_id}")
def delete_testing_schedule(sched_id: int, db: Session = Depends(get_db)):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(sched)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROL EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/exceptions/")
def list_exceptions(db: Session = Depends(get_db)):
    rows = db.query(models.ControlException).order_by(models.ControlException.created_at.desc()).all()
    result = []
    for r in rows:
        ctrl = db.query(models.Control).filter(models.Control.id == r.control_id).first() if r.control_id else None
        if r.status == "Approved" and r.expiry_date and r.expiry_date < datetime.datetime.utcnow():
            r.status = "Expired"
            db.commit()
        result.append({
            "id": r.id, "title": r.title, "control_id": r.control_id,
            "control_name": ctrl.name if ctrl else None,
            "reason": r.reason, "compensating_control": r.compensating_control,
            "risk_owner": r.risk_owner, "approver": r.approver, "status": r.status,
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/exceptions/")
def create_exception(
    title: str = Body(...),
    reason: str = Body(...),
    risk_owner: str = Body(...),
    control_id: Optional[int] = Body(None),
    compensating_control: Optional[str] = Body(None),
    approver: Optional[str] = Body(None),
    expiry_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    exp_dt = datetime.datetime.fromisoformat(expiry_date) if expiry_date else None
    exc = models.ControlException(
        title=title, reason=reason, risk_owner=risk_owner, control_id=control_id,
        compensating_control=compensating_control, approver=approver, expiry_date=exp_dt,
    )
    db.add(exc)
    db.commit()
    db.refresh(exc)
    return {"id": exc.id}


@app.patch("/exceptions/{exc_id}")
def update_exception(
    exc_id: int,
    status: Optional[str] = Body(None),
    approver: Optional[str] = Body(None),
    compensating_control: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    exc = db.query(models.ControlException).filter(models.ControlException.id == exc_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Not found")
    if status is not None:
        exc.status = status
    if approver is not None:
        exc.approver = approver
    if compensating_control is not None:
        exc.compensating_control = compensating_control
    db.commit()
    return {"ok": True}


@app.delete("/exceptions/{exc_id}")
def delete_exception(exc_id: int, db: Session = Depends(get_db)):
    exc = db.query(models.ControlException).filter(models.ControlException.id == exc_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(exc)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT FINDINGS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/audit-findings/")
def list_audit_findings(db: Session = Depends(get_db)):
    rows = db.query(models.AuditFinding).order_by(models.AuditFinding.created_at.desc()).all()
    result = []
    for r in rows:
        dept = db.query(models.Department).filter(models.Department.id == r.department_id).first() if r.department_id else None
        result.append({
            "id": r.id, "title": r.title, "description": r.description,
            "severity": r.severity, "source": r.source, "framework_ref": r.framework_ref,
            "owner": r.owner, "department_id": r.department_id,
            "department_name": dept.name if dept else None,
            "status": r.status,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "remediation_notes": r.remediation_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/audit-findings/")
def create_audit_finding(
    title: str = Body(...),
    description: str = Body(...),
    severity: str = Body("Major"),
    source: str = Body("Internal"),
    framework_ref: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    department_id: Optional[int] = Body(None),
    due_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    due_dt = datetime.datetime.fromisoformat(due_date) if due_date else None
    finding = models.AuditFinding(
        title=title, description=description, severity=severity, source=source,
        framework_ref=framework_ref, owner=owner, department_id=department_id, due_date=due_dt,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return {"id": finding.id}


@app.patch("/audit-findings/{finding_id}")
def update_audit_finding(
    finding_id: int,
    status: Optional[str] = Body(None),
    remediation_notes: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    due_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    finding = db.query(models.AuditFinding).filter(models.AuditFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Not found")
    if status is not None:
        finding.status = status
    if remediation_notes is not None:
        finding.remediation_notes = remediation_notes
    if owner is not None:
        finding.owner = owner
    if due_date is not None:
        finding.due_date = datetime.datetime.fromisoformat(due_date)
    db.commit()
    return {"ok": True}


@app.delete("/audit-findings/{finding_id}")
def delete_audit_finding(finding_id: int, db: Session = Depends(get_db)):
    finding = db.query(models.AuditFinding).filter(models.AuditFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(finding)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR RISK
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/vendors/")
def list_vendors(db: Session = Depends(get_db)):
    rows = db.query(models.Vendor).order_by(models.Vendor.created_at.desc()).all()
    return [{
        "id": v.id, "name": v.name, "service_type": v.service_type,
        "criticality": v.criticality, "handles_pii": v.handles_pii,
        "risk_rating": v.risk_rating,
        "last_assessment_date": v.last_assessment_date.isoformat() if v.last_assessment_date else None,
        "next_review_date": v.next_review_date.isoformat() if v.next_review_date else None,
        "contact_name": v.contact_name, "contact_email": v.contact_email,
        "status": v.status, "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in rows]


@app.post("/vendors/")
def create_vendor(
    name: str = Body(...),
    service_type: str = Body(...),
    criticality: str = Body("Medium"),
    handles_pii: bool = Body(False),
    risk_rating: str = Body("Medium"),
    contact_name: Optional[str] = Body(None),
    contact_email: Optional[str] = Body(None),
    last_assessment_date: Optional[str] = Body(None),
    next_review_date: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    v = models.Vendor(
        name=name, service_type=service_type, criticality=criticality,
        handles_pii=handles_pii, risk_rating=risk_rating,
        contact_name=contact_name, contact_email=contact_email,
        last_assessment_date=datetime.datetime.fromisoformat(last_assessment_date) if last_assessment_date else None,
        next_review_date=datetime.datetime.fromisoformat(next_review_date) if next_review_date else None,
        notes=notes,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id}


@app.patch("/vendors/{vendor_id}")
def update_vendor(
    vendor_id: int,
    risk_rating: Optional[str] = Body(None),
    criticality: Optional[str] = Body(None),
    status: Optional[str] = Body(None),
    last_assessment_date: Optional[str] = Body(None),
    next_review_date: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    handles_pii: Optional[bool] = Body(None),
    db: Session = Depends(get_db),
):
    v = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    if risk_rating is not None: v.risk_rating = risk_rating
    if criticality is not None: v.criticality = criticality
    if status is not None: v.status = status
    if handles_pii is not None: v.handles_pii = handles_pii
    if notes is not None: v.notes = notes
    if last_assessment_date is not None:
        v.last_assessment_date = datetime.datetime.fromisoformat(last_assessment_date)
    if next_review_date is not None:
        v.next_review_date = datetime.datetime.fromisoformat(next_review_date)
    db.commit()
    return {"ok": True}


@app.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: int, db: Session = Depends(get_db)):
    v = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(v)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE HEATMAP
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/heatmap")
def get_compliance_heatmap(db: Session = Depends(get_db)):
    departments = db.query(models.Department).all()
    categories = sorted(set(
        r[0] for r in db.query(models.Control.category).distinct().all() if r[0]
    ))
    matrix = []
    for dept in departments:
        row = []
        for cat in categories:
            evidences = (
                db.query(models.Evidence)
                .join(models.Control, models.Evidence.control_id == models.Control.id)
                .filter(models.Evidence.department_id == dept.id)
                .filter(models.Control.category == cat)
                .all()
            )
            total  = len(evidences)
            passed = sum(1 for e in evidences if e.status and e.status.lower() in ("pass", "compliant"))
            pct    = round(passed / total * 100, 1) if total > 0 else None
            row.append(pct)
        matrix.append(row)
    return {
        "departments": [{"id": d.id, "name": d.name} for d in departments],
        "categories": categories,
        "matrix": matrix,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/reports/generate")
def generate_report(db: Session = Depends(get_db)):
    output_path = "uploads/Noryx_Compliance_Report.pdf"
    reporting.generate_pdf_report(db, output_path)
    return FileResponse(output_path, media_type="application/pdf", filename="Noryx_Compliance_Report.pdf")        if not admin:
            db.add(models.User(
                username="admin",
                password_hash=auth.get_password_hash("admin123"),
                role="admin"
            ))

        # Seed Employee User
        employee = db.query(models.User).filter(models.User.username == "employee").first()
        if not employee:
            db.add(models.User(
                username="employee",
                password_hash=auth.get_password_hash("emp123"),
                role="employee",
                department_id=dept.id
            ))
        db.commit()

        # Auto-load NCA controls from nca_controls.json if DB has no controls yet
        if db.query(models.Control).count() == 0:
            _seed_nca_controls(db)
    finally:
        db.close()


def _seed_nca_controls(db):
    """Load nca_controls.json and seed controls + departments into the DB."""
    search_paths = [
        Path(__file__).parent / "nca_controls.json",
        Path(__file__).parent.parent / "nca_controls.json",
        Path(__file__).parent.parent.parent / "nca_controls.json",
    ]
    nca_path = next((p for p in search_paths if p.exists()), None)
    if nca_path is None:
        return

    try:
        items = json.loads(nca_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(items, list):
        return

    departments_by_name = _ensure_mapping_departments(db)
    due_date = datetime.datetime(2025, 12, 31, 23, 59, 59)

    for item in items:
        if not isinstance(item, dict):
            continue
        name        = (item.get("name")        or "").strip()
        description = (item.get("description") or "").strip()
        criteria    = (item.get("criteria")    or "").strip()
        if not name:
            continue

        dept_id, dept_name, _ = _classify_control_to_department(
            name, description, criteria, departments_by_name,
        )

        ctrl = models.Control(
            name=name,
            description=description,
            criteria=criteria,
            category=dept_name,
            department_id=dept_id,
        )
        db.add(ctrl)
        db.flush()

        db.add(models.Task(
            title=f"Implement & evidence control {name}",
            department_id=dept_id,
            control_id=ctrl.id,
            due_date=due_date,
            status="Pending",
        ))

    db.commit()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_framework_db():
    db = framework_library_db.SessionLocal()
    try:
        yield db
    finally:
        db.close()

os.makedirs("uploads", exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# DEPARTMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/departments/", response_model=schemas.Department)
def create_department(dept: schemas.DepartmentCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Department).filter(models.Department.name == dept.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists")
    db_dept = models.Department(**dept.dict())
    db.add(db_dept)
    db.commit()
    db.refresh(db_dept)
    return db_dept

@app.get("/departments/", response_model=List[schemas.Department])
def list_departments(db: Session = Depends(get_db)):
    return db.query(models.Department).all()

@app.delete("/departments/{dept_id}")
def delete_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(models.Department).filter(models.Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(dept)
    db.commit()
    return {"message": "Deleted"}

@app.get("/departments/{dept_id}/controls", response_model=List[schemas.Control])
def get_dept_controls(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Control).filter(models.Control.department_id == dept_id).all()

@app.get("/departments/{dept_id}/employees", response_model=List[schemas.Employee])
def get_dept_employees(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Employee).filter(models.Employee.department_id == dept_id).all()


# ═══════════════════════════════════════════════════════════════════════════════
# EMPLOYEES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/employees/", response_model=schemas.Employee)
def create_employee(emp: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    db_emp = models.Employee(**emp.dict())
    db.add(db_emp)
    db.commit()
    db.refresh(db_emp)
    return db_emp

@app.get("/employees/", response_model=List[schemas.Employee])
def list_employees(db: Session = Depends(get_db)):
    return db.query(models.Employee).all()


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROLS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/controls/", response_model=schemas.Control)
def create_control(control: schemas.ControlCreate, db: Session = Depends(get_db)):
    db_ctrl = models.Control(**control.dict())
    db.add(db_ctrl)
    db.commit()
    db.refresh(db_ctrl)
    return db_ctrl

@app.get("/controls/", response_model=List[schemas.Control])
def list_controls(db: Session = Depends(get_db)):
    return db.query(models.Control).all()

@app.patch("/controls/{control_id}", response_model=schemas.Control)
def update_control(control_id: int, update: schemas.ControlUpdate, db: Session = Depends(get_db)):
    ctrl = db.query(models.Control).filter(models.Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")
    if update.department_id is not None:
        ctrl.department_id = update.department_id
    if update.category is not None:
        ctrl.category = update.category
    db.commit()
    db.refresh(ctrl)
    return ctrl


# ═══════════════════════════════════════════════════════════════════════════════
# DYNAMIC NCA UPLOAD + AUTO DEPARTMENT MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

# Each entry: (department_name, description, keyword_list).
# Order matters only for tie-breaking; classifier picks the highest-scoring match.
DEPT_KEYWORD_MAP: List[tuple] = [
    ("Network Security", "Firewalls, segmentation, VPN, perimeter and traffic controls", [
        "firewall","network","dmz","vpn","router","switch","port","traffic","segment",
        "inbound","outbound","packet","proxy","waf","ids","ips","intrusion","perimeter",
        "subnet","vlan","nat","dns","dhcp","bandwidth","wireless","wi-fi","wifi",
    ]),
    ("Identity & Access", "Authentication, MFA, privileged access, identity governance", [
        "mfa","password","authentication","authorization","access","privilege","account",
        "identity","iam","login","credential","permission","active directory","ldap",
        "sso","oauth","pam","least privilege","group policy",
    ]),
    ("Endpoint Protection", "Antivirus, EDR, patching, endpoint hardening", [
        "antivirus","malware","endpoint","device","patch","edr","definition","scan",
        "quarantine","real-time","hotfix","cve","remediat","mobile device","byod",
    ]),
    ("Data Security", "Encryption, classification, DLP, backup and recovery", [
        "encrypt","backup","database","classif","dlp","bitlocker","tls","ssl","storage",
        "transit","at rest","key management","certificate","sensitive","confidential",
        "retention","archive","restore","recovery","rpo","rto","data leakage",
    ]),
    ("Incident Response", "Detection, SIEM, forensics, breach handling", [
        "incident","alert","log","siem","monitor","detect","forensic","investigation",
        "threat","attack","breach","correlation","triage","ioc","playbook","escalat",
        "contain","eradicate","soc",
    ]),
    ("Compliance & Governance", "Policy, audit, governance, regulatory compliance", [
        "audit","compliance","policy","procedure","governance","regulation","standard",
        "framework","nca","ecc","gdpr","iso","nist","review","exception","waiver",
        "report","strategy","steering committee","authorized official","documented","approved",
    ]),
    ("Risk Management", "Risk assessment, mitigation strategy, risk register", [
        "risk","threat assessment","likelihood","impact","mitigation","tolerance",
        "appetite","risk register",
    ]),
    ("Human Resources", "Personnel security, training, awareness, HR processes", [
        "personnel","training","awareness","employee","staff","onboarding","termination",
        "hire","leaver","background check","screening","contract","disciplinar",
        "saudi cybersecurity","positions shall be filled","human resources","full-time",
    ]),
    ("IT Operations", "Infrastructure, configuration, change and asset management", [
        "server","infrastructure","configuration","change management","asset",
        "inventory","operating system","datacenter","virtuali","container","docker",
        "kubernetes","ci/cd","devops","deployment","capacity",
    ]),
    ("Physical Security", "Facility access, CCTV, hardware and media security", [
        "physical","facility","cctv","camera","badge","door","access card","lock",
        "guard","visitor","building","server room","clean desk","shredding","disposal",
        "media","usb","removable",
    ]),
    ("Vendor & Third-Party Management", "Third-party / supplier risk and contracts", [
        "third party","third-party","vendor","supplier","outsourc","sla","contract management",
    ]),
    ("Cloud & Hosting", "Cloud workloads, SaaS/IaaS/PaaS, hosting", [
        "cloud","saas","iaas","paas","aws","azure","gcp","tenant","hosting",
    ]),
    ("Business Continuity", "BCP, disaster recovery, resilience", [
        "business continuity","bcp","disaster recovery","drp","resilien","contingency",
    ]),
    ("Application Security", "Secure SDLC, code review, app pen-testing", [
        "application security","secure coding","sdlc","code review","penetration test",
        "owasp","api security","web application",
    ]),
]

DEFAULT_FALLBACK_DEPT = "Compliance & Governance"

# NCA ECC control families are deterministic — every sub-control in a family
# (e.g. 2-5-1, 2-5-2, 2-5-3, 2-5-4) shares the same business owner. Keyword
# scoring splits families because boilerplate words ("documented", "implemented",
# "periodically reviewed") shift the winner sub-control-by-sub-control. Use this
# explicit map for any control whose name matches the NCA family pattern.
import re as _re
_NCA_PATTERN = _re.compile(r"^(\d+-\d+)-\d+$")
NCA_FAMILY_TO_DEPT: Dict[str, str] = {
    "1-1":  "Compliance & Governance",
    "1-2":  "Compliance & Governance",
    "1-3":  "Compliance & Governance",
    "1-4":  "Compliance & Governance",
    "1-5":  "Risk Management",
    "1-6":  "IT Operations",
    "1-7":  "Compliance & Governance",
    "1-8":  "Compliance & Governance",
    "1-9":  "Human Resources",
    "1-10": "Human Resources",
    "2-1":  "IT Operations",
    "2-2":  "Identity & Access",
    "2-3":  "Endpoint Protection",
    "2-4":  "Network Security",
    "2-5":  "Network Security",
    "2-6":  "Endpoint Protection",
    "2-7":  "Data Security",
    "2-8":  "Data Security",
    "2-9":  "Data Security",
    "2-10": "Endpoint Protection",
    "2-11": "Application Security",
    "2-12": "Incident Response",
    "2-13": "Incident Response",
    "2-14": "Physical Security",
    "2-15": "Application Security",
    "3-1":  "Business Continuity",
    "4-1":  "Vendor & Third-Party Management",
    "4-2":  "Cloud & Hosting",
}


def _nca_family_department(name: str) -> Optional[str]:
    if not name:
        return None
    m = _NCA_PATTERN.match(name.strip())
    if not m:
        return None
    return NCA_FAMILY_TO_DEPT.get(m.group(1))


def _classify_control_to_department(
    name: str,
    description: str,
    criteria: str,
    departments_by_name: Dict[str, models.Department],
) -> tuple:
    """Resolve a control to its owning department.

    1. If the control name matches the NCA ECC family pattern (e.g. "2-5-1"),
       use the deterministic family map — this keeps sub-controls together.
    2. Otherwise, fall back to keyword scoring on name + description + criteria.
    Returns (department_id, department_name, score).
    """
    nca_dept = _nca_family_department(name)
    if nca_dept and nca_dept in departments_by_name:
        dept = departments_by_name[nca_dept]
        return dept.id, nca_dept, 999  # high score = exact-match marker

    text_blob = f"{name or ''} {description or ''} {criteria or ''}".lower()
    best_name, best_score = None, 0
    for dept_name, _desc, kws in DEPT_KEYWORD_MAP:
        score = sum(1 for kw in kws if kw in text_blob)
        if score > best_score:
            best_score, best_name = score, dept_name

    if best_name is None or best_score == 0:
        best_name = DEFAULT_FALLBACK_DEPT

    dept = departments_by_name.get(best_name)
    return (dept.id if dept else None), best_name, best_score


def _ensure_mapping_departments(db: Session) -> Dict[str, models.Department]:
    """Make sure every department referenced by the keyword map exists, then
    return a {name → Department} index for fast lookup."""
    for dept_name, desc, _kws in DEPT_KEYWORD_MAP:
        existing = (
            db.query(models.Department)
            .filter(models.Department.name == dept_name)
            .first()
        )
        if not existing:
            db.add(models.Department(name=dept_name, description=desc))
    db.commit()
    return {d.name: d for d in db.query(models.Department).all()}


@app.post("/admin/controls/clear")
def admin_clear_all_controls(db: Session = Depends(get_db)):
    """Wipe all controls + dependent tasks/evidence/risks so the admin starts
    with a zero-control state before uploading a fresh NCA dataset."""
    n_risks    = db.query(models.Risk).delete(synchronize_session=False)
    n_evidence = db.query(models.Evidence).delete(synchronize_session=False)
    n_tasks    = db.query(models.Task).delete(synchronize_session=False)
    n_controls = db.query(models.Control).delete(synchronize_session=False)
    db.commit()
    return {
        "controls_deleted": n_controls,
        "tasks_deleted":    n_tasks,
        "evidence_deleted": n_evidence,
        "risks_deleted":    n_risks,
    }


@app.post("/admin/controls/upload-nca")
async def admin_upload_nca_controls(
    file: UploadFile = File(...),
    deadline: str = Form(...),
    replace_existing: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Admin-side upload of nca_controls_dataset.json.

    - Parses the JSON (expects a list of {name, description, criteria}).
    - Auto-classifies every control into a department by keyword matching.
    - Creates a Control row + a Task row (with the supplied deadline) per entry.
    - When `replace_existing` is true (default), wipes existing controls first
      so totals start at zero, matching the requested admin workflow.
    """
    try:
        raw = await file.read()
        items = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="JSON root must be an array of controls.")

    try:
        if len(deadline) <= 10:
            due_date = datetime.datetime.fromisoformat(deadline + "T23:59:59")
        else:
            due_date = datetime.datetime.fromisoformat(deadline.replace("Z", ""))
    except Exception:
        raise HTTPException(status_code=400, detail="deadline must be ISO 8601 (YYYY-MM-DD or full datetime).")

    if replace_existing:
        db.query(models.Risk).delete(synchronize_session=False)
        db.query(models.Evidence).delete(synchronize_session=False)
        db.query(models.Task).delete(synchronize_session=False)
        db.query(models.Control).delete(synchronize_session=False)
        db.commit()

    departments_by_name = _ensure_mapping_departments(db)

    controls_created     = 0
    controls_skipped     = 0
    tasks_created        = 0
    department_assignments: Dict[str, int] = {}
    sample_assignments: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        name        = (item.get("name")        or "").strip()
        description = (item.get("description") or "").strip()
        criteria    = (item.get("criteria")    or "").strip()
        if not name:
            continue

        if not replace_existing:
            existing = db.query(models.Control).filter(models.Control.name == name).first()
            if existing:
                controls_skipped += 1
                continue

        dept_id, dept_name, score = _classify_control_to_department(
            name, description, criteria, departments_by_name,
        )

        ctrl = models.Control(
            name=name,
            description=description,
            criteria=criteria,
            category=dept_name,
            department_id=dept_id,
        )
        db.add(ctrl)
        db.flush()  # need ctrl.id for the task row

        task = models.Task(
            title=f"Implement & evidence control {name}",
            department_id=dept_id,
            control_id=ctrl.id,
            due_date=due_date,
            status="Pending",
        )
        db.add(task)

        controls_created += 1
        tasks_created    += 1
        department_assignments[dept_name] = department_assignments.get(dept_name, 0) + 1
        if len(sample_assignments) < 8:
            sample_assignments.append({
                "control": name,
                "department": dept_name,
                "match_score": score,
            })

    db.commit()

    return {
        "controls_created":          controls_created,
        "controls_skipped_existing": controls_skipped,
        "tasks_created":             tasks_created,
        "deadline":                  due_date.isoformat(),
        "replaced_existing":         replace_existing,
        "departments": [
            {"name": k, "controls_assigned": v}
            for k, v in sorted(department_assignments.items(), key=lambda x: -x[1])
        ],
        "sample_assignments": sample_assignments,
    }


@app.get("/tasks/summary")
def tasks_summary(db: Session = Depends(get_db)):
    """Per-department progress used by the modernised Task Management UI."""
    now = datetime.datetime.utcnow()
    rows = []
    for d in db.query(models.Department).order_by(models.Department.name).all():
        total = db.query(models.Task).filter(models.Task.department_id == d.id).count()
        if total == 0:
            continue
        completed   = db.query(models.Task).filter(models.Task.department_id == d.id, models.Task.status == "Completed").count()
        in_progress = db.query(models.Task).filter(models.Task.department_id == d.id, models.Task.status == "In Progress").count()
        overdue     = db.query(models.Task).filter(
            models.Task.department_id == d.id,
            models.Task.status != "Completed",
            models.Task.due_date < now,
        ).count()
        rows.append({
            "department_id":   d.id,
            "department_name": d.name,
            "total":           total,
            "completed":       completed,
            "in_progress":     in_progress,
            "pending":         total - completed - in_progress,
            "overdue":         overdue,
            "progress_pct":    round((completed / total) * 100, 1) if total else 0.0,
        })
    rows.sort(key=lambda r: -r["total"])

    overall_total     = sum(r["total"] for r in rows)
    overall_completed = sum(r["completed"] for r in rows)
    return {
        "overall": {
            "total":        overall_total,
            "completed":    overall_completed,
            "progress_pct": round((overall_completed / overall_total) * 100, 1) if overall_total else 0.0,
        },
        "departments": rows,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ISOLATED FRAMEWORK LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════

def _framework_control_dict(control):
    return {
        "id": control.id,
        "framework_key": control.framework_key,
        "framework_name": control.framework_name,
        "version": control.version,
        "control_id": control.control_id,
        "title": control.title,
        "domain": control.domain,
        "category": control.category,
        "control_text": control.control_text,
        "source_file": control.source_file,
        "page": control.page,
    }


def _framework_mapping_dict(mapping):
    return {
        "id": mapping.id,
        "source_framework": mapping.source_framework,
        "source_control_id": mapping.source_control_id,
        "source_control_title": mapping.source_control_title,
        "target_framework": mapping.target_framework,
        "target_control_id": mapping.target_control_id,
        "scf_control_id": mapping.scf_control_id,
        "scf_control_title": mapping.scf_control_title,
        "relationship_type": mapping.relationship_type,
        "match_score": mapping.match_score,
        "notes": mapping.notes,
    }


def _policy_document_dict(document):
    return {
        "id": document.id,
        "company_name": document.company_name,
        "document_type": document.document_type,
        "original_filename": document.original_filename,
        "stored_filename": document.stored_filename,
        "stored_path": document.stored_path,
        "content_type": document.content_type,
        "file_size": document.file_size,
        "notes": document.notes,
        "uploaded_by": document.uploaded_by,
        "uploaded_at": document.uploaded_at,
    }


@app.get("/framework-library/summary")
def framework_library_summary(db: Session = Depends(get_framework_db)):
    control_counts = (
        db.query(
            framework_library_db.FrameworkControl.framework_key,
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.version,
            func.count(framework_library_db.FrameworkControl.id),
        )
        .group_by(
            framework_library_db.FrameworkControl.framework_key,
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.version,
        )
        .order_by(framework_library_db.FrameworkControl.framework_name)
        .all()
    )
    mapping_counts = (
        db.query(
            framework_library_db.FrameworkMapping.target_framework,
            func.count(framework_library_db.FrameworkMapping.id),
        )
        .group_by(framework_library_db.FrameworkMapping.target_framework)
        .order_by(framework_library_db.FrameworkMapping.target_framework)
        .all()
    )
    return {
        "source_count": db.query(framework_library_db.FrameworkSource).count(),
        "total_controls": db.query(framework_library_db.FrameworkControl).count(),
        "total_mappings": db.query(framework_library_db.FrameworkMapping).count(),
        "database": str(framework_library_db.FRAMEWORK_DB_PATH),
        "framework_counts": [
            {
                "framework_key": key,
                "framework_name": name,
                "version": version,
                "controls": count,
            }
            for key, name, version, count in control_counts
        ],
        "mapping_counts": [
            {"target_framework": target, "mappings": count}
            for target, count in mapping_counts
        ],
    }


@app.get("/framework-library/sources")
def framework_library_sources(db: Session = Depends(get_framework_db)):
    sources = (
        db.query(framework_library_db.FrameworkSource)
        .order_by(framework_library_db.FrameworkSource.framework_name)
        .all()
    )
    return [
        {
            "id": src.id,
            "framework_key": src.framework_key,
            "framework_name": src.framework_name,
            "version": src.version,
            "owner": src.owner,
            "raw_format": src.raw_format,
            "source_filename": src.source_filename,
            "stored_path": src.stored_path,
            "imported_at": src.imported_at,
            "control_count": src.control_count,
            "mapping_count": src.mapping_count,
        }
        for src in sources
    ]


@app.get("/framework-library/controls")
def framework_library_controls(
    framework: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_framework_db),
):
    limit = min(max(limit, 1), 300)
    offset = max(offset, 0)
    query = db.query(framework_library_db.FrameworkControl)
    if framework:
        query = query.filter(
            or_(
                framework_library_db.FrameworkControl.framework_key == framework,
                framework_library_db.FrameworkControl.framework_name.ilike(f"%{framework}%"),
            )
        )
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkControl.control_id.ilike(like),
                framework_library_db.FrameworkControl.title.ilike(like),
                framework_library_db.FrameworkControl.domain.ilike(like),
                framework_library_db.FrameworkControl.control_text.ilike(like),
            )
        )
    total = query.count()
    items = (
        query.order_by(
            framework_library_db.FrameworkControl.framework_name,
            framework_library_db.FrameworkControl.control_id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_framework_control_dict(item) for item in items],
    }


@app.get("/framework-library/mappings")
def framework_library_mappings(
    framework: Optional[str] = None,
    target_framework: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_framework_db),
):
    limit = min(max(limit, 1), 300)
    offset = max(offset, 0)
    query = db.query(framework_library_db.FrameworkMapping)
    if framework:
        like = f"%{framework}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkMapping.source_framework.ilike(like),
                framework_library_db.FrameworkMapping.target_framework.ilike(like),
            )
        )
    if target_framework:
        query = query.filter(framework_library_db.FrameworkMapping.target_framework.ilike(f"%{target_framework}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                framework_library_db.FrameworkMapping.source_control_id.ilike(like),
                framework_library_db.FrameworkMapping.source_control_title.ilike(like),
                framework_library_db.FrameworkMapping.target_control_id.ilike(like),
                framework_library_db.FrameworkMapping.scf_control_id.ilike(like),
                framework_library_db.FrameworkMapping.scf_control_title.ilike(like),
            )
        )
    total = query.count()
    items = (
        query.order_by(
            framework_library_db.FrameworkMapping.target_framework,
            framework_library_db.FrameworkMapping.target_control_id,
            framework_library_db.FrameworkMapping.scf_control_id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_framework_mapping_dict(item) for item in items],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# COMPANY POLICY DOCUMENTS (ISOLATED UPLOADS)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/policy-documents/upload")
def upload_policy_document(
    company_name: str = Form(...),
    document_type: str = Form("Policy Pack"),
    notes: Optional[str] = Form(""),
    uploaded_by: Optional[str] = Form("Admin"),
    file: UploadFile = File(...),
    db: Session = Depends(get_framework_db),
):
    if not company_name.strip():
        raise HTTPException(status_code=400, detail="company_name is required")

    original = Path(file.filename or "policy-document").name
    suffix = Path(original).suffix.lower()
    allowed = {".pdf", ".docx", ".doc", ".txt"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, DOC, and TXT policy files are supported")

    stored_filename = f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:10]}{suffix}"
    stored_path = framework_library_db.POLICY_UPLOAD_DIR / stored_filename

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = framework_library_db.PolicyDocument(
        company_name=company_name.strip(),
        document_type=(document_type or "Policy Pack").strip(),
        original_filename=original,
        stored_filename=stored_filename,
        stored_path=str(stored_path.relative_to(framework_library_db.PROJECT_ROOT)),
        content_type=file.content_type or "",
        file_size=stored_path.stat().st_size,
        notes=(notes or "").strip(),
        uploaded_by=(uploaded_by or "Admin").strip(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return _policy_document_dict(document)


@app.get("/policy-documents")
def list_policy_documents(
    company_name: Optional[str] = None,
    db: Session = Depends(get_framework_db),
):
    query = db.query(framework_library_db.PolicyDocument)
    if company_name:
        query = query.filter(framework_library_db.PolicyDocument.company_name.ilike(f"%{company_name}%"))
    documents = query.order_by(framework_library_db.PolicyDocument.uploaded_at.desc()).all()
    return [_policy_document_dict(document) for document in documents]


@app.get("/policy-documents/assessment-frameworks")
def policy_assessment_frameworks(db: Session = Depends(get_framework_db)):
    return {
        "items": policy_assessment.get_assessable_frameworks(db),
        "default_selection": "all",
        "engine": policy_assessment.ENGINE_NAME,
        "engines": policy_assessment.get_assessment_engines(),
    }


@app.post("/policy-documents/{document_id}/assess")
def assess_policy_document(
    document_id: int,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    db: Session = Depends(get_framework_db),
):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    selected = (payload or {}).get("frameworks") or ["all"]
    engine = (payload or {}).get("engine") or policy_assessment.ENGINE_NAME
    try:
        return policy_assessment.assess_policy_document(db, document, selected, engine=engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/policy-documents/{document_id}/assessment-report")
def get_policy_assessment_report(
    document_id: int,
    frameworks: Optional[str] = None,
    engine: Optional[str] = None,
    db: Session = Depends(get_framework_db),
):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    selected = [item.strip() for item in frameworks.split(",")] if frameworks else ["all"]
    try:
        assessment = policy_assessment.assess_policy_document(db, document, selected, engine=engine)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    report_name = f"policy-assessment-{document.id}-{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}.pdf"
    report_path = framework_library_db.POLICY_REPORT_DIR / report_name
    policy_assessment.build_assessment_pdf(assessment, report_path)
    download_name = f"{Path(document.original_filename).stem}-assessment-report.pdf"
    return FileResponse(report_path, media_type="application/pdf", filename=download_name)


@app.get("/policy-documents/{document_id}/file")
def get_policy_document_file(document_id: int, db: Session = Depends(get_framework_db)):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    path = framework_library_db.PROJECT_ROOT / document.stored_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Policy document file not found")
    return FileResponse(path, media_type=document.content_type or None, filename=document.original_filename)


@app.delete("/policy-documents/{document_id}")
def delete_policy_document(document_id: int, db: Session = Depends(get_framework_db)):
    document = (
        db.query(framework_library_db.PolicyDocument)
        .filter(framework_library_db.PolicyDocument.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Policy document not found")

    path = framework_library_db.PROJECT_ROOT / document.stored_path
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    db.delete(document)
    db.commit()
    return {"message": "Policy document deleted", "document_id": document_id}


# ═══════════════════════════════════════════════════════════════════════════════
# EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/evidence/upload/")
def upload_evidence(
    control_id:    int            = Form(...),
    department_id: Optional[int]  = Form(None),
    employee_name: Optional[str]  = Form("Unknown"),
    file:          UploadFile     = File(...),
    db:            Session        = Depends(get_db),
):
    import ai_engine

    ctrl = db.query(models.Control).filter(models.Control.id == control_id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Control not found")

    file_location = f"uploads/{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Pass full context: criteria keywords + description so category detection
    # can match words like "firewall" that appear only in the description field
    full_context = f"{ctrl.criteria or ''} {ctrl.description or ''}".strip()
    status, extracted_text, confidence = ai_engine.validate_evidence(file_location, full_context)

    # Multi-tier workflow: anything not "pass" is queued for manager review
    review_state = "auto" if status.lower() == "pass" else "pending_manager"

    db_ev = models.Evidence(
        control_id=control_id,
        department_id=department_id,
        employee_name=employee_name,
        file_path=file_location,
        status=status,
        extracted_text=extracted_text,
        ai_confidence=confidence,
        ai_status=status,
        review_state=review_state,
    )
    db.add(db_ev)
    db.commit()
    db.refresh(db_ev)

    # AUTOMATED RISK TRIGGER – create a risk entry when evidence fails
    if status.lower() == "fail":
        db_risk = models.Risk(
            title=f"AI Validation Failure: Control #{control_id}",
            description=f"Automated risk created due to invalid evidence upload by {employee_name}.",
            control_id=control_id,
            evidence_id=db_ev.id,
            impact="High",
            likelihood="Medium",
            status="Open"
        )
        db.add(db_risk)
        db.commit()

    return {
        "message": "File uploaded and validated",
        "evidence_id": db_ev.id,
        "status": status,
        "confidence": confidence,
        "extracted_text": extracted_text,
        "review_state": review_state,
    }

@app.get("/evidence/", response_model=List[schemas.Evidence])
def list_evidence(db: Session = Depends(get_db)):
    return db.query(models.Evidence).order_by(models.Evidence.upload_time.desc()).all()

@app.post("/evidence/{evidence_id}/review")
def review_evidence(evidence_id: int, final_status: str = Form(...), db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    ev.status = final_status
    db.commit()
    if final_status.lower() in ["pass", "fail"]:
        dataset_dir = f"dataset/train/{final_status.lower()}"
        os.makedirs(dataset_dir, exist_ok=True)
        shutil.copy(ev.file_path, os.path.join(dataset_dir, os.path.basename(ev.file_path)))
    return {"message": f"Evidence marked as {final_status}"}


# ─── Multi-tier approval workflow ────────────────────────────────────────────

@app.get("/evidence/pending-review", response_model=List[schemas.Evidence])
def list_pending_review(db: Session = Depends(get_db)):
    """Evidence items waiting on manager action."""
    return (
        db.query(models.Evidence)
          .filter(models.Evidence.review_state == "pending_manager")
          .order_by(models.Evidence.upload_time.desc())
          .all()
    )


@app.get("/evidence/{evidence_id}", response_model=schemas.Evidence)
def get_evidence(evidence_id: int, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return ev


@app.get("/evidence/{evidence_id}/file")
def get_evidence_file(evidence_id: int, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev or not ev.file_path or not os.path.exists(ev.file_path):
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return FileResponse(ev.file_path)


@app.delete("/evidence/{evidence_id}")
def delete_evidence(evidence_id: int, db: Session = Depends(get_db)):
    """Drop an uploaded evidence: removes the file, the auto-created risk, and the row."""
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")

    # Detach any risks created from this evidence
    risks = db.query(models.Risk).filter(models.Risk.evidence_id == ev.id).all()
    for r in risks:
        db.delete(r)

    # Best-effort file cleanup — don't fail the delete if the file is gone
    try:
        if ev.file_path and os.path.exists(ev.file_path):
            os.remove(ev.file_path)
    except OSError:
        pass

    db.delete(ev)
    db.commit()
    return {"message": "Evidence deleted", "evidence_id": evidence_id}


@app.post("/evidence/{evidence_id}/manager-approve", response_model=schemas.Evidence)
def manager_approve(evidence_id: int, payload: schemas.ManagerApprove, db: Session = Depends(get_db)):
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not (payload.justification or "").strip():
        raise HTTPException(status_code=400, detail="Justification is required to override AI verdict")

    final = (payload.final_status or "pass").lower()
    if final not in ("pass", "fail"):
        raise HTTPException(status_code=400, detail="final_status must be 'pass' or 'fail'")

    ev.status                = final
    ev.review_state          = "approved"
    ev.manager_decision      = "approved"
    ev.manager_justification = payload.justification.strip()
    ev.reviewed_by           = payload.reviewer or "Manager"
    ev.reviewed_at           = datetime.datetime.utcnow()

    # If manager approves a previously-failed item as passing, close the auto-created risk
    if final == "pass":
        risks = db.query(models.Risk).filter(models.Risk.evidence_id == ev.id).all()
        for r in risks:
            r.status = "Closed"
            r.mitigation_strategy = (r.mitigation_strategy or "") + \
                f"\n[Manager override {ev.reviewed_at.isoformat()}]: {ev.manager_justification}"

    db.commit()
    db.refresh(ev)
    return ev


@app.post("/evidence/{evidence_id}/manager-reject", response_model=schemas.Evidence)
def manager_reject(evidence_id: int, payload: schemas.ManagerSendBack, db: Session = Depends(get_db)):
    """Send the submission back to the employee with comments."""
    ev = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if not (payload.comment or "").strip():
        raise HTTPException(status_code=400, detail="A comment is required when sending evidence back")

    ev.review_state     = "sent_back"
    ev.manager_decision = "sent_back"
    ev.manager_comment  = payload.comment.strip()
    ev.reviewed_by      = payload.reviewer or "Manager"
    ev.reviewed_at      = datetime.datetime.utcnow()
    db.commit()
    db.refresh(ev)
    return ev


@app.get("/departments/{dept_id}/sent-back", response_model=List[schemas.Evidence])
def list_sent_back_for_department(dept_id: int, db: Session = Depends(get_db)):
    """Evidence the manager sent back to this department."""
    return (
        db.query(models.Evidence)
          .filter(models.Evidence.department_id == dept_id,
                  models.Evidence.review_state == "sent_back")
          .order_by(models.Evidence.reviewed_at.desc().nullslast())
          .all()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    evidences = db.query(models.Evidence).all()
    departments = db.query(models.Department).all()

    total   = len(evidences)
    passed  = sum(1 for e in evidences if e.status and e.status.lower() == "pass")
    failed  = sum(1 for e in evidences if e.status and e.status.lower() == "fail")
    review  = sum(1 for e in evidences if e.status and e.status.lower() == "need_review")
    overall = round((passed / total * 100) if total > 0 else 0, 1)

    dept_stats = []
    for dept in departments:
        d_ev = [e for e in evidences if e.department_id == dept.id]
        d_total  = len(d_ev)
        d_pass   = sum(1 for e in d_ev if e.status and e.status.lower() == "pass")
        d_fail   = sum(1 for e in d_ev if e.status and e.status.lower() == "fail")
        d_review = sum(1 for e in d_ev if e.status and e.status.lower() == "need_review")
        d_pct    = round((d_pass / d_total * 100) if d_total > 0 else 0, 1)
        dept_stats.append({
            "department": dept.name,
            "total": d_total,
            "passed": d_pass,
            "failed": d_fail,
            "review": d_review,
            "compliance_pct": d_pct,
        })

    # Top failing controls
    controls = db.query(models.Control).all()
    fail_map = {}
    for e in evidences:
        if e.status and e.status.lower() == "fail":
            fail_map[e.control_id] = fail_map.get(e.control_id, 0) + 1
    top_failing = sorted(
        [{"control": next((c.name for c in controls if c.id == cid), "Unknown"),
          "fails": cnt} for cid, cnt in fail_map.items()],
        key=lambda x: x["fails"], reverse=True
    )[:5]

    return {
        "overall_compliance": overall,
        "total_evidence": total,
        "total_pass": passed,
        "total_fail": failed,
        "total_review": review,
        "department_stats": dept_stats,
        "top_failing_controls": top_failing,
    }


@app.get("/dashboard/threats")
def dashboard_threats(
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    For every control that has at least one failed evidence submission,
    run the threat prediction model and return a ranked list of cyber threats
    (most dangerous first). Also returns per-severity counts and the
    most-at-risk department.

    If `department_id` is supplied, the analysis is scoped to controls
    assigned to that department (used by the Employee Overview).
    """
    import threat_predictor

    evidences   = db.query(models.Evidence).filter(
        models.Evidence.status.ilike("fail")
    ).all()
    controls    = db.query(models.Control).all()
    departments = db.query(models.Department).all()

    # Scope to department's assigned controls when requested.
    if department_id is not None:
        scoped_ctrl_ids = {c.id for c in controls if c.department_id == department_id}
        controls  = [c for c in controls if c.id in scoped_ctrl_ids]
        evidences = [e for e in evidences if e.control_id in scoped_ctrl_ids]

    # Build a map: control_id → fail count
    fail_counts: dict[int, int] = {}
    for ev in evidences:
        fail_counts[ev.control_id] = fail_counts.get(ev.control_id, 0) + 1

    if not fail_counts:
        return {
            "threats": [],
            "severity_counts": {"Critical": 0, "High": 0, "Medium": 0, "Low": 0},
            "total_failed_controls": 0,
            "most_at_risk_department": None,
        }

    ctrl_map = {c.id: c for c in controls}
    dept_map = {d.id: d for d in departments}

    # Dept → fail counts (for most-at-risk calculation)
    dept_fail: dict[int, int] = {}
    for ev in evidences:
        if ev.department_id:
            dept_fail[ev.department_id] = dept_fail.get(ev.department_id, 0) + 1

    most_at_risk_dept = None
    if dept_fail and department_id is None:
        worst_id = max(dept_fail, key=dept_fail.get)
        most_at_risk_dept = dept_map.get(worst_id, {}).name if worst_id in dept_map else None

    # Aggregate threats across all failed controls; deduplicate by technique_id,
    # keeping the highest combined_score seen for each technique.
    seen: dict[str, dict] = {}

    for ctrl_id, fail_count in fail_counts.items():
        ctrl = ctrl_map.get(ctrl_id)
        if not ctrl:
            continue

        dept_name = dept_map.get(ctrl.department_id).name if ctrl.department_id in dept_map else "Unassigned"

        preds = threat_predictor.predict_threats(
            control_name=ctrl.name or "",
            control_description=ctrl.description or "",
            control_category=ctrl.category or "",
            top_n=4,
        )

        for pred in preds:
            tid = pred["technique_id"]
            entry = {
                **pred,
                "triggered_by": ctrl.name,
                "department":   dept_name,
                "fail_count":   fail_count,
            }
            if tid not in seen or pred["combined_score"] > seen[tid]["combined_score"]:
                seen[tid] = entry

    # Sort all unique threats by combined_score descending
    threat_list = sorted(seen.values(), key=lambda x: x["combined_score"], reverse=True)

    # Severity counts
    sev_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for t in threat_list:
        label = t.get("severity_label", "Low")
        if label in sev_counts:
            sev_counts[label] += 1

    return {
        "threats":                threat_list,
        "severity_counts":        sev_counts,
        "total_failed_controls":  len(fail_counts),
        "most_at_risk_department": most_at_risk_dept,
    }


@app.get("/dashboard/stats/{dept_id}")
def department_stats(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(models.Department).filter(models.Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    evidences = db.query(models.Evidence).filter(models.Evidence.department_id == dept_id).all()
    controls  = db.query(models.Control).filter(models.Control.department_id == dept_id).all()

    total   = len(evidences)
    passed  = sum(1 for e in evidences if e.status and e.status.lower() == "pass")
    failed  = sum(1 for e in evidences if e.status and e.status.lower() == "fail")
    review  = sum(1 for e in evidences if e.status and e.status.lower() == "need_review")
    overall = round((passed / total * 100) if total > 0 else 0, 1)

    fail_map = {}
    for e in evidences:
        if e.status and e.status.lower() == "fail":
            fail_map[e.control_id] = fail_map.get(e.control_id, 0) + 1
    top_failing = sorted(
        [{"control": next((c.name for c in controls if c.id == cid), "Unknown"),
          "fails": cnt} for cid, cnt in fail_map.items()],
        key=lambda x: x["fails"], reverse=True
    )[:5]

    return {
        "department": dept.name,
        "department_id": dept_id,
        "overall_compliance": overall,
        "total_evidence": total,
        "total_pass": passed,
        "total_fail": failed,
        "total_review": review,
        "total_controls": len(controls),
        "top_failing_controls": top_failing,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION & USERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        username=user.username,
        password_hash=hashed_password,
        role=user.role,
        department_id=user.department_id
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/auth/login", response_model=schemas.Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})

    access_token_expires = auth.timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role, "username": user.username}

@app.get("/users/me", response_model=schemas.User)
def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


# ═══════════════════════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/tasks/", response_model=schemas.Task)
def create_task(task: schemas.TaskCreate, db: Session = Depends(get_db)):
    db_task = models.Task(**task.dict())
    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    # MOCK EMAIL ALERT (FR3)
    dept = db.query(models.Department).filter(models.Department.id == db_task.department_id).first()
    dept_name = dept.name if dept else "Unknown"
    print("\n" + "="*60)
    print("📧 MOCK EMAIL ALERT TRIGGERED (FR3)")
    print(f"To: technical-staff@{dept_name.lower().replace(' ', '')}.company.com")
    print(f"Subject: New Compliance Task Assigned: TSK-{db_task.id}")
    print("Body:")
    print(f"A new task '{db_task.title}' has been assigned to your department.")
    print(f"Due Date: {db_task.due_date}")
    print("Please log in to the Noryx platform to submit your evidence.")
    print("="*60 + "\n")

    return db_task

@app.get("/tasks/", response_model=List[schemas.Task])
def list_tasks(db: Session = Depends(get_db)):
    return db.query(models.Task).all()

@app.get("/departments/{dept_id}/tasks", response_model=List[schemas.Task])
def get_dept_tasks(dept_id: int, db: Session = Depends(get_db)):
    return db.query(models.Task).filter(models.Task.department_id == dept_id).all()

@app.patch("/tasks/{task_id}", response_model=schemas.Task)
def update_task(task_id: int, status: str, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = status
    db.commit()
    db.refresh(task)
    return task


# ═══════════════════════════════════════════════════════════════════════════════
# RISKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/risks/", response_model=schemas.Risk)
def create_risk(risk: schemas.RiskCreate, db: Session = Depends(get_db)):
    db_risk = models.Risk(**risk.dict())
    db.add(db_risk)
    db.commit()
    db.refresh(db_risk)
    return db_risk

@app.get("/risks/", response_model=List[schemas.Risk])
def list_risks(db: Session = Depends(get_db)):
    return db.query(models.Risk).all()

@app.patch("/risks/{risk_id}", response_model=schemas.Risk)
def update_risk(risk_id: int, mitigation_strategy: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    risk = db.query(models.Risk).filter(models.Risk.id == risk_id).first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk not found")
    if mitigation_strategy is not None:
        risk.mitigation_strategy = mitigation_strategy
    if status is not None:
        risk.status = status
    db.commit()
    db.refresh(risk)
    return risk


# ═══════════════════════════════════════════════════════════════════════════════
# TESTING SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

_FREQ_DAYS = {"monthly": 30, "quarterly": 90, "biannually": 180, "annually": 365}

def _next_due(last: datetime.datetime | None, frequency: str) -> datetime.datetime:
    days = _FREQ_DAYS.get(frequency, 90)
    base = last or datetime.datetime.utcnow()
    return base + datetime.timedelta(days=days)


@app.get("/testing-schedules/")
def list_testing_schedules(db: Session = Depends(get_db)):
    rows = db.query(models.TestingSchedule).all()
    result = []
    for r in rows:
        ctrl = db.query(models.Control).filter(models.Control.id == r.control_id).first()
        result.append({
            "id": r.id,
            "control_id": r.control_id,
            "control_name": ctrl.name if ctrl else None,
            "control_category": ctrl.category if ctrl else None,
            "frequency": r.frequency,
            "last_tested_at": r.last_tested_at.isoformat() if r.last_tested_at else None,
            "next_due_at": r.next_due_at.isoformat() if r.next_due_at else None,
            "owner": r.owner,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/testing-schedules/")
def create_testing_schedule(
    control_id: int = Body(...),
    frequency: str = Body("quarterly"),
    owner: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    existing = db.query(models.TestingSchedule).filter(models.TestingSchedule.control_id == control_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Schedule already exists for this control")
    next_due = _next_due(None, frequency)
    sched = models.TestingSchedule(
        control_id=control_id,
        frequency=frequency,
        owner=owner,
        notes=notes,
        next_due_at=next_due,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return {"id": sched.id, "next_due_at": sched.next_due_at.isoformat()}


@app.post("/testing-schedules/{sched_id}/mark-tested")
def mark_tested(sched_id: int, db: Session = Depends(get_db)):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    now = datetime.datetime.utcnow()
    sched.last_tested_at = now
    sched.next_due_at = _next_due(now, sched.frequency)
    db.commit()
    db.refresh(sched)
    return {"last_tested_at": sched.last_tested_at.isoformat(), "next_due_at": sched.next_due_at.isoformat()}


@app.patch("/testing-schedules/{sched_id}")
def update_testing_schedule(
    sched_id: int,
    frequency: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Not found")
    if frequency is not None:
        sched.frequency = frequency
        sched.next_due_at = _next_due(sched.last_tested_at, frequency)
    if owner is not None:
        sched.owner = owner
    if notes is not None:
        sched.notes = notes
    db.commit()
    return {"ok": True}


@app.delete("/testing-schedules/{sched_id}")
def delete_testing_schedule(sched_id: int, db: Session = Depends(get_db)):
    sched = db.query(models.TestingSchedule).filter(models.TestingSchedule.id == sched_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(sched)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROL EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/exceptions/")
def list_exceptions(db: Session = Depends(get_db)):
    rows = db.query(models.ControlException).order_by(models.ControlException.created_at.desc()).all()
    result = []
    for r in rows:
        ctrl = db.query(models.Control).filter(models.Control.id == r.control_id).first() if r.control_id else None
        # Auto-expire
        if r.status == "Approved" and r.expiry_date and r.expiry_date < datetime.datetime.utcnow():
            r.status = "Expired"
            db.commit()
        result.append({
            "id": r.id, "title": r.title, "control_id": r.control_id,
            "control_name": ctrl.name if ctrl else None,
            "reason": r.reason, "compensating_control": r.compensating_control,
            "risk_owner": r.risk_owner, "approver": r.approver, "status": r.status,
            "expiry_date": r.expiry_date.isoformat() if r.expiry_date else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/exceptions/")
def create_exception(
    title: str = Body(...),
    reason: str = Body(...),
    risk_owner: str = Body(...),
    control_id: Optional[int] = Body(None),
    compensating_control: Optional[str] = Body(None),
    approver: Optional[str] = Body(None),
    expiry_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    exp_dt = datetime.datetime.fromisoformat(expiry_date) if expiry_date else None
    exc = models.ControlException(
        title=title, reason=reason, risk_owner=risk_owner, control_id=control_id,
        compensating_control=compensating_control, approver=approver, expiry_date=exp_dt,
    )
    db.add(exc)
    db.commit()
    db.refresh(exc)
    return {"id": exc.id}


@app.patch("/exceptions/{exc_id}")
def update_exception(
    exc_id: int,
    status: Optional[str] = Body(None),
    approver: Optional[str] = Body(None),
    compensating_control: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    exc = db.query(models.ControlException).filter(models.ControlException.id == exc_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Not found")
    if status is not None:
        exc.status = status
    if approver is not None:
        exc.approver = approver
    if compensating_control is not None:
        exc.compensating_control = compensating_control
    db.commit()
    return {"ok": True}


@app.delete("/exceptions/{exc_id}")
def delete_exception(exc_id: int, db: Session = Depends(get_db)):
    exc = db.query(models.ControlException).filter(models.ControlException.id == exc_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(exc)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT FINDINGS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/audit-findings/")
def list_audit_findings(db: Session = Depends(get_db)):
    rows = db.query(models.AuditFinding).order_by(models.AuditFinding.created_at.desc()).all()
    result = []
    for r in rows:
        dept = db.query(models.Department).filter(models.Department.id == r.department_id).first() if r.department_id else None
        result.append({
            "id": r.id, "title": r.title, "description": r.description,
            "severity": r.severity, "source": r.source, "framework_ref": r.framework_ref,
            "owner": r.owner, "department_id": r.department_id,
            "department_name": dept.name if dept else None,
            "status": r.status,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "remediation_notes": r.remediation_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@app.post("/audit-findings/")
def create_audit_finding(
    title: str = Body(...),
    description: str = Body(...),
    severity: str = Body("Major"),
    source: str = Body("Internal"),
    framework_ref: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    department_id: Optional[int] = Body(None),
    due_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    due_dt = datetime.datetime.fromisoformat(due_date) if due_date else None
    finding = models.AuditFinding(
        title=title, description=description, severity=severity, source=source,
        framework_ref=framework_ref, owner=owner, department_id=department_id, due_date=due_dt,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return {"id": finding.id}


@app.patch("/audit-findings/{finding_id}")
def update_audit_finding(
    finding_id: int,
    status: Optional[str] = Body(None),
    remediation_notes: Optional[str] = Body(None),
    owner: Optional[str] = Body(None),
    due_date: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    finding = db.query(models.AuditFinding).filter(models.AuditFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Not found")
    if status is not None:
        finding.status = status
    if remediation_notes is not None:
        finding.remediation_notes = remediation_notes
    if owner is not None:
        finding.owner = owner
    if due_date is not None:
        finding.due_date = datetime.datetime.fromisoformat(due_date)
    db.commit()
    return {"ok": True}


@app.delete("/audit-findings/{finding_id}")
def delete_audit_finding(finding_id: int, db: Session = Depends(get_db)):
    finding = db.query(models.AuditFinding).filter(models.AuditFinding.id == finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(finding)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR RISK
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/vendors/")
def list_vendors(db: Session = Depends(get_db)):
    rows = db.query(models.Vendor).order_by(models.Vendor.created_at.desc()).all()
    return [{
        "id": v.id, "name": v.name, "service_type": v.service_type,
        "criticality": v.criticality, "handles_pii": v.handles_pii,
        "risk_rating": v.risk_rating,
        "last_assessment_date": v.last_assessment_date.isoformat() if v.last_assessment_date else None,
        "next_review_date": v.next_review_date.isoformat() if v.next_review_date else None,
        "contact_name": v.contact_name, "contact_email": v.contact_email,
        "status": v.status, "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in rows]


@app.post("/vendors/")
def create_vendor(
    name: str = Body(...),
    service_type: str = Body(...),
    criticality: str = Body("Medium"),
    handles_pii: bool = Body(False),
    risk_rating: str = Body("Medium"),
    contact_name: Optional[str] = Body(None),
    contact_email: Optional[str] = Body(None),
    last_assessment_date: Optional[str] = Body(None),
    next_review_date: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    db: Session = Depends(get_db),
):
    v = models.Vendor(
        name=name, service_type=service_type, criticality=criticality,
        handles_pii=handles_pii, risk_rating=risk_rating,
        contact_name=contact_name, contact_email=contact_email,
        last_assessment_date=datetime.datetime.fromisoformat(last_assessment_date) if last_assessment_date else None,
        next_review_date=datetime.datetime.fromisoformat(next_review_date) if next_review_date else None,
        notes=notes,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id}


@app.patch("/vendors/{vendor_id}")
def update_vendor(
    vendor_id: int,
    risk_rating: Optional[str] = Body(None),
    criticality: Optional[str] = Body(None),
    status: Optional[str] = Body(None),
    last_assessment_date: Optional[str] = Body(None),
    next_review_date: Optional[str] = Body(None),
    notes: Optional[str] = Body(None),
    handles_pii: Optional[bool] = Body(None),
    db: Session = Depends(get_db),
):
    v = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    if risk_rating is not None: v.risk_rating = risk_rating
    if criticality is not None: v.criticality = criticality
    if status is not None: v.status = status
    if handles_pii is not None: v.handles_pii = handles_pii
    if notes is not None: v.notes = notes
    if last_assessment_date is not None:
        v.last_assessment_date = datetime.datetime.fromisoformat(last_assessment_date)
    if next_review_date is not None:
        v.next_review_date = datetime.datetime.fromisoformat(next_review_date)
    db.commit()
    return {"ok": True}


@app.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: int, db: Session = Depends(get_db)):
    v = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not v:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(v)
    db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE HEATMAP
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard/heatmap")
def get_compliance_heatmap(db: Session = Depends(get_db)):
    departments = db.query(models.Department).all()
    categories = sorted(set(
        r[0] for r in db.query(models.Control.category).distinct().all() if r[0]
    ))
    matrix = []
    for dept in departments:
        row = []
        for cat in categories:
            evidences = (
                db.query(models.Evidence)
                .join(models.Control, models.Evidence.control_id == models.Control.id)
                .filter(models.Evidence.department_id == dept.id)
                .filter(models.Control.category == cat)
                .all()
            )
            total  = len(evidences)
            passed = sum(1 for e in evidences if e.status and e.status.lower() in ("pass", "compliant"))
            pct    = round(passed / total * 100, 1) if total > 0 else None
            row.append(pct)
        matrix.append(row)
    return {
        "departments": [{"id": d.id, "name": d.name} for d in departments],
        "categories": categories,
        "matrix": matrix,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/reports/generate")
def generate_report(db: Session = Depends(get_db)):
    output_path = "uploads/Noryx_Compliance_Report.pdf"
    reporting.generate_pdf_report(db, output_path)
    return FileResponse(output_path, media_type="application/pdf", filename="Noryx_Compliance_Report.pdf")
