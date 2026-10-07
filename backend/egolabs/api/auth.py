"""Sign-in. People sign in with Google (`/auth/google`). The owner (`OWNER_EMAIL`, else the first account) is
the only admin; everyone else starts with no access (`pending`) until the owner gives them a role. Every
sign-in is kept, with where it came from. Email and password sign-in exists for scripts and tests only,
behind the `PASSWORD_LOGIN` setting."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from egolabs import google_auth, owner
from egolabs.api.deps import DbSession, SignedInUser
from egolabs.config import get_settings
from egolabs.events import record_event
from egolabs.models import Role, SignIn, User
from egolabs.schemas import (
    GoogleConfig,
    GoogleSignIn,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from egolabs.security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Serialises registrations so exactly one user can become the first admin.
_REGISTER_LOCK_KEY = 0x45474F_0001


def _token_response(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserRead.model_validate(user))


def _create_user(db: Session, email: str, name: str | None, via: str, **fields: object) -> User:
    """Make an account (caller holds the registration lock): the owner is admin, anyone else waits for access."""
    is_owner = owner.new_account_is_owner(db, email)
    user = User(
        email=email, name=name, role=Role.admin if is_owner else Role.pending, is_owner=is_owner, **fields
    )
    db.add(user)
    db.flush()
    record_event(
        db,
        "user.registered",
        f"User registered: {email}" + (" (owner, admin)" if is_owner else " (waiting for access)"),
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        data={"role": user.role.value, "via": via},
    )
    return user


def _client(request: Request) -> tuple[str | None, str | None]:
    """The browser's address and user agent. The web app signs people in from its server and passes them on
    (Cloudflare's CF-Connecting-IP, else the first X-Forwarded-For hop); the API itself isn't public."""
    ip = (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    )
    ip = ip or (request.client.host if request.client else None)
    agent = request.headers.get("user-agent")
    return (ip[:64] if ip else None), (agent[:512] if agent else None)


def _signed_in(db: Session, user: User, method: str, request: Request) -> TokenResponse:
    ip, agent = _client(request)
    db.add(SignIn(user_id=user.id, method=method, ip=ip, user_agent=agent))
    user.last_sign_in_at = datetime.now(UTC)
    db.commit()
    return _token_response(user)


def _password_login_enabled() -> None:
    if not get_settings().password_login:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Email and password sign-in is turned off; sign in with Google"
        )


@router.get("/google", response_model=GoogleConfig)
def google_config() -> GoogleConfig:
    """What the login page needs to send people to Google (no secrets)."""
    s = get_settings()
    enabled = google_auth.configured()
    return GoogleConfig(enabled=enabled, client_id=s.google_client_id if enabled else None,
                        authorize_url=s.google_authorize_url)  # fmt: skip


@router.post("/google", response_model=TokenResponse)
def google_sign_in(body: GoogleSignIn, db: DbSession, request: Request) -> TokenResponse:
    """Finish signing in with Google: the code from Google's redirect becomes a session. The account is
    found by its Google id, else linked by its (Google-verified) email, else created."""
    if not google_auth.configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in isn't set up")
    try:
        who = google_auth.sign_in(body.code, body.redirect_uri, body.code_verifier)
    except google_auth.GoogleSignInError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _REGISTER_LOCK_KEY})
    user = db.scalar(select(User).where(User.google_sub == who.sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == who.email))
        if user is not None and user.google_sub is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This email belongs to an account linked to another Google account"
            )
        if user is not None:
            user.google_sub = who.sub
        else:
            user = _create_user(db, who.email, who.name, "google", google_sub=who.sub)
    owner.sync(db, user)
    if not user.is_active:
        db.commit()  # keep an owner hand-over; the account itself stays out
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    if user.name is None and who.name:
        user.name = who.name
    return _signed_in(db, user, "google", request)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: DbSession, request: Request) -> TokenResponse:
    """Create an account with a password (only with `PASSWORD_LOGIN` on, for scripts and tests)."""
    _password_login_enabled()
    email = body.email.lower()
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _REGISTER_LOCK_KEY})
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = _create_user(db, email, body.name or None, "password", password_hash=hash_password(body.password))
    return _signed_in(db, user, "password", request)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DbSession, request: Request) -> TokenResponse:
    """Sign in with a password (only with `PASSWORD_LOGIN` on, for scripts and tests)."""
    _password_login_enabled()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or user.password_hash is None:
        verify_password(body.password, DUMMY_HASH)  # same timing as a wrong password
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    owner.sync(db, user)
    if not user.is_active:
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")
    return _signed_in(db, user, "password", request)


@router.get("/me", response_model=UserRead)
def me(user: SignedInUser) -> User:
    """The signed-in account, also while it waits for access (its role is then `pending`)."""
    return user
