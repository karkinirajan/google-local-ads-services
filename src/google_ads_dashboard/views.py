"""Routes: sign in with Google, the dashboard, a user's ads data, sign out."""

from __future__ import annotations

import hmac
import logging
import re
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from .extensions import db
from .google import GoogleError
from .models import GoogleAdsAccount, User, utcnow

logger = logging.getLogger(__name__)
bp = Blueprint("views", __name__)

ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")
TOKEN_SKEW_SECONDS = 60  # refresh a little before the access token really expires


def services():
    return current_app.extensions["ads_dashboard"]


def is_admin(user: User) -> bool:
    return user.email.lower() in services().settings.admin_emails


def can_view(viewer: User, target_id: str) -> bool:
    """Your own data, or anyone's if you are one of ADMIN_EMAILS."""
    return viewer.id == target_id or is_admin(viewer)


# -- CSRF for the one form (sign out): a random token in the session that the form must send back
def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@bp.app_context_processor
def template_globals():
    return {"csrf_token": csrf_token, "is_admin": is_admin}


@bp.before_app_request
def check_csrf():
    if request.method == "POST":
        expected, got = session.get("csrf_token", ""), request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected, got):
            abort(400, "The form has expired. Go back, reload the page and try again.")


# -- pages
@bp.get("/")
def index():
    """Nobody is listed to a visitor who is not signed in (the first version listed every user's email)."""
    if not current_user.is_authenticated:
        return render_template("index.html", rows=None)
    if is_admin(current_user):
        users = db.session.scalars(select(User).order_by(User.name)).all()
    else:
        users = [current_user]
    rows = [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "customer_ids": ", ".join(a.customer_id for a in u.accounts) or "Not available",
        }
        for u in users
    ]
    return render_template("index.html", rows=rows)


@bp.get("/healthz")
def healthz():
    return {"status": "ok"}


@bp.get("/ads-data/<user_id>")
@login_required
def ads_data(user_id: str):
    if not can_view(current_user, user_id):
        abort(403, "You can only see your own Google Ads data.")
    target = db.session.get(User, user_id)
    if target is None:
        abort(404, "No such user.")

    campaigns, problems = [], []
    try:
        token = fresh_access_token(target)
    except GoogleError as exc:
        token = None
        problems.append(str(exc))
    if token is None and not problems:
        problems.append("The Google access for this user has expired. They need to sign in again.")
    if token is not None:
        for account in target.accounts:
            try:
                campaigns.extend(services().ads.campaigns(token, account.customer_id))
            except GoogleError as exc:
                problems.append(str(exc))
    return render_template("ads_data.html", user=target, campaigns=campaigns, problems=problems)


def fresh_access_token(user: User) -> str | None:
    """The user's access token, refreshed when it is about to expire; None if it cannot be refreshed."""
    expiry = user.token_expiry
    if user.access_token and expiry and (expiry - utcnow()).total_seconds() > TOKEN_SKEW_SECONDS:
        return user.access_token
    if not user.refresh_token:
        return None
    tokens = services().oauth.refresh(user.refresh_token)
    user.save_tokens(tokens["access_token"], tokens.get("refresh_token"), int(tokens["expires_in"]))
    db.session.commit()
    return user.access_token


# -- sign in / out
@bp.get("/login")
def login():
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    try:
        return redirect(services().oauth.authorization_url(state))
    except GoogleError as exc:
        abort(502, str(exc))


@bp.get("/login/callback")
def callback():
    oauth = services().oauth
    expected = session.pop("oauth_state", "")
    got = request.args.get("state", "")
    if not expected or not hmac.compare_digest(expected, got):
        # Without this check anyone could make a victim's browser finish a sign-in the attacker started
        abort(400, "The sign-in could not be verified (state mismatch). Please try again.")
    if error := request.args.get("error"):
        reason = error if ERROR_CODE.match(error) else "error"
        abort(400, f"Google did not complete the sign-in ({reason}).")
    code = request.args.get("code")
    if not code:
        abort(400, "Google sent no authorization code.")

    try:
        tokens = oauth.exchange_code(code)
        info = oauth.userinfo(tokens["access_token"])
    except GoogleError as exc:
        abort(502, str(exc))
    if not info.get("email_verified") or not info.get("sub") or not info.get("email"):
        abort(400, "Google did not give a verified email address for this account.")

    user = db.session.get(User, str(info["sub"]))
    if user is None:
        user = User(id=str(info["sub"]), name="", email="")
        db.session.add(user)
        logger.info("New user created")
    user.email = str(info["email"])
    user.name = str(info.get("given_name") or info.get("name") or info["email"])[:100]
    user.profile_pic = info.get("picture")
    user.save_tokens(tokens["access_token"], tokens.get("refresh_token"), int(tokens["expires_in"]))
    db.session.commit()

    session.clear()  # a new session for the signed-in user (no fixation)
    login_user(user)
    store_customer_ids(user)
    return redirect(url_for("views.index"))


def store_customer_ids(user: User) -> None:
    """Remember which Google Ads accounts the user can reach. A failure must not break the sign-in."""
    try:
        ids = services().ads.list_accessible_customers(user.access_token)
    except GoogleError as exc:
        logger.warning("Could not list the Google Ads accounts: %s", exc)
        return
    known = {a.customer_id for a in user.accounts}
    for customer_id in ids:
        if customer_id not in known:
            db.session.add(GoogleAdsAccount(user_id=user.id, customer_id=customer_id))
    db.session.commit()


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("views.index"))
