import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.models.user import User
from app.models.tenant import Tenant
from app.models.property import Property

db = SessionLocal()
try:
    user = db.query(User).filter_by(email="xayihin554@nuitx.com", is_deleted=False).first()
    print(f"User: {user.id if user else None}")

    if user:
        tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
        print(f"Tenant: {tenant.name if tenant else None}")

        props = db.query(Property).filter_by(tenant_id=user.tenant_id).limit(1).count()
        print(f"Properties: {props}")

    print("All queries OK")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
finally:
    db.close()
