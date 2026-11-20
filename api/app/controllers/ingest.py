from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser, get_business, get_current_user
from app.models import (Business, Document, Gstr2bEntry, Gstr3bDraft, ItcCheck, Match, PipelineRun, PurchaseInvoice, SalesSummary, Vendor, VendorNotice)
from app.schemas.views import Detail
from app.services import ingest, pipeline

router = APIRouter(prefix="/ingest", tags=["intake"])


@router.post("", response_model=Detail)
async def upload_files(purchase_register: UploadFile | None = File(None), gstr2b: UploadFile | None = File(None), sales: UploadFile | None = File(None),
                       db: Session = Depends(get_db), business: Business = Depends(get_business)):
    """Upload the purchase register (csv/xlsx), GSTR-2B (xlsx B2B sheet) and the sales summary (csv). Then the processing layers run."""
    if not (purchase_register or gstr2b or sales):
        raise HTTPException(400, "Send at least one file")
    result, months = {}, set()
    try:
        for key, up, fn in (("register", purchase_register, ingest.ingest_purchase_register), ("gstr2b", gstr2b, ingest.ingest_gstr2b), ("sales", sales, ingest.ingest_sales_summary)):
            if up:
                r = fn(db, business, await up.read(), up.filename or "")
                result[key] = r
                months |= set(r["months"])
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"Could not read the file: {exc}") from exc
    runs = [pipeline.run_pipeline(db, business.id, m) for m in sorted(months)]
    return {"files": result, "months": sorted(months), "pipeline": [{"month": r.month, "status": r.status, "total_ms": r.total_ms} for r in runs]}


@router.delete("/all", response_model=Detail)
def delete_all_data(db: Session = Depends(get_db), business: Business = Depends(get_business), user: CurrentUser = Depends(get_current_user)):
    """Deletes every uploaded file, invoice, match, decision, draft and scan of this business only. The sign-in stays and the workspace is blank again."""
    files = [d.file_uri for d in db.query(Document).filter_by(business_id=business.id).all() if d.file_uri]
    counts = {}
    for model in (VendorNotice, ItcCheck, Match, Gstr3bDraft, PipelineRun, SalesSummary, Gstr2bEntry, PurchaseInvoice, Document, Vendor):  # children first
        if not inspect(db.get_bind()).has_table(model.__tablename__):
            continue
        counts[model.__tablename__] = db.query(model).filter_by(business_id=business.id).delete(synchronize_session=False)
        db.flush()
    if not user.demo:
        business.gstin = ""  # learned again from the next GSTR-2B
    db.commit()
    for f in files:
        try:
            Path(f).unlink(missing_ok=True)
        except OSError:
            pass
    return {"deleted": True, "rows": counts}
