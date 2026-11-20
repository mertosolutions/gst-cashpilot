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
    demo: bool = False  # True only for the built-in demo accounts (X-Demo-User); they get sample data, real Google sign-ins start empty


_CERT_CACHE: dict[str, tuple[float, object]] = {}


def _google_request():
    """A Request that gives up after 4 s and keeps Google's signing keys for an hour, so a slow network cannot stall every call."""
    import time
    from google.auth.transport import requests as grequests

    class _Cached(grequests.Request):
        def __call__(self, url, method="GET", body=None, headers=None, timeout=4, **kwargs):
            hit = _CERT_CACHE.get(url)
            if hit and time.time() - hit[0] < 3600:
                return hit[1]
            res = super().__call__(url, method=method, body=body, headers=headers, timeout=min(timeout, 4), **kwargs)
            if method == "GET" and getattr(res, "status", 0) == 200:
                _CERT_CACHE[url] = (time.time(), res)
            return res

    return _Cached()


def get_current_user(authorization: str | None = Header(default=None), x_demo_user: str | None = Header(default=None)) -> CurrentUser:
    s = get_settings()
    has_bearer = bool(authorization and authorization.lower().startswith("bearer "))
    if s.auth_mode == "firebase" or has_bearer:
        if not has_bearer:
            raise HTTPException(401, "Missing Firebase ID token")
        if not s.firebase_project_id:
            raise HTTPException(500, "FIREBASE_PROJECT_ID is not configured")
        from google.oauth2 import id_token
        try:
            token = authorization.split(" ", 1)[1]  # type: ignore[union-attr]
            claims = id_token.verify_firebase_token(token, _google_request(), audience=s.firebase_project_id)
        except Exception as exc:  # noqa: BLE001
            from google.auth.exceptions import TransportError
            if isinstance(exc, TransportError):
                raise HTTPException(503, "Could not reach Google to verify your sign-in. Try again.") from exc
            raise HTTPException(401, "Could not verify your sign-in. Sign in again and retry.") from exc
        if not claims:
            raise HTTPException(401, "Invalid Firebase token")
        return CurrentUser(uid=claims["sub"], email=claims.get("email"), name=claims.get("name"))
    return CurrentUser(uid=(x_demo_user or s.demo_owner_uid).strip()[:64], name="Demo user", demo=True)


def get_business(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Business:
    b = db.query(Business).filter_by(owner_uid=user.uid).first()
    if not b:
        from app.seed.generator import BUYER
        from app.seed.load import seed
        b = Business(owner_uid=user.uid, gstin=BUYER if user.demo else "", legal_name=(user.name or user.email or "My business")[:100])
        db.add(b)
        db.commit()
        set_tenant(db, b.id)
        if user.demo:  # a real user starts with a blank workspace and uploads their own files
            try:
                seed(db, uid=user.uid)
            except Exception:
                pass
    set_tenant(db, b.id)
    return b
