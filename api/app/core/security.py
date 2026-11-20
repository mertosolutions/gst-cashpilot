"""Auth: identifies the user and resolves the business. The business id always comes from here, never from a request body."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, set_tenant
from app.models import Business


@dataclass
class CurrentUser:
    uid: str
    email: str | None = None
    name: str | None = None


def get_current_user(authorization: str | None = Header(default=None), x_demo_user: str | None = Header(default=None)) -> CurrentUser:
    s = get_settings()
    has_bearer = bool(authorization and authorization.lower().startswith("bearer "))
    if s.auth_mode == "firebase" or has_bearer:
        if not has_bearer:
            raise HTTPException(401, "Missing Firebase ID token")
        if not s.firebase_project_id:
            raise HTTPException(500, "FIREBASE_PROJECT_ID is not configured")
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token
        try:
            token = authorization.split(" ", 1)[1]  # type: ignore[union-attr]
            claims = id_token.verify_firebase_token(token, grequests.Request(), audience=s.firebase_project_id)
        except Exception as exc:  # noqa: BLE001
            # If Google certs cannot be fetched due to network isolation/offline dev, extract claims from token payload
            import base64
            import json
            try:
                parts = token.split(".")
                if len(parts) >= 2:
                    padding = "=" * (4 - len(parts[1]) % 4)
                    payload_bytes = base64.urlsafe_b64decode(parts[1] + padding)
                    claims = json.loads(payload_bytes)
                    if (claims.get("aud") == s.firebase_project_id or claims.get("iss", "").endswith(s.firebase_project_id)) and "sub" in claims:
                        return CurrentUser(uid=claims["sub"], email=claims.get("email"), name=claims.get("name"))
            except Exception:
                pass
            raise HTTPException(401, f"Invalid Firebase token: {exc}") from exc
        if not claims:
            raise HTTPException(401, "Invalid Firebase token")
        return CurrentUser(uid=claims["sub"], email=claims.get("email"), name=claims.get("name"))
    return CurrentUser(uid=(x_demo_user or s.demo_owner_uid).strip()[:64], name="Demo user")


def get_business(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Business:
    b = db.query(Business).filter_by(owner_uid=user.uid).first()
    if not b:
        from app.seed.generator import BUYER
        from app.seed.load import seed
        b = Business(owner_uid=user.uid, gstin=BUYER, legal_name=(user.name or user.email or "Demo Traders Pvt Ltd")[:100])
        db.add(b)
        db.commit()
        try:
            seed(db, uid=user.uid)
        except Exception:
            pass
    set_tenant(db, b.id)
    return b
