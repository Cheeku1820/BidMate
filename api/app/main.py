from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.router import router as auth_router
from app.db import get_db
from app.errors import DomainError, domain_error_handler

app = FastAPI(title="Takeoff API")
app.add_exception_handler(DomainError, domain_error_handler)
app.include_router(auth_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("select 1"))
    return {"status": "ok", "database": "ok"}
