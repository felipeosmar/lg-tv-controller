"""
Google OAuth2 authentication for LG TV Controller.
Uses aiohttp-session with encrypted cookies.
"""

import json
import logging
import os
import secrets
from urllib.parse import urlencode

import aiohttp as _aiohttp
from aiohttp import web
from aiohttp_session import get_session, setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
# Emails permitidos (comma-separated). Vazio = qualquer conta Google.
ALLOWED_EMAILS = [
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
]
# Secret key para criptografar cookies de sessão (32 bytes url-safe base64)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = Fernet.generate_key().decode()
    logger.warning("SESSION_SECRET não definido — gerado aleatório (sessões não sobrevivem restart)")

# Google OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = "openid email profile"

# Rotas que NÃO precisam de autenticação
PUBLIC_PATHS = {"/login", "/auth/callback", "/auth/logout"}


def is_auth_configured() -> bool:
    """Verifica se OAuth está configurado."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


# ─── Middleware ───────────────────────────────────────────────

@web.middleware
async def auth_middleware(request, handler):
    """Protege rotas — redireciona para /login se não autenticado."""
    if not is_auth_configured():
        # OAuth não configurado — acesso livre
        return await handler(request)

    path = request.path
    # Permitir rotas públicas e assets
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return await handler(request)

    session = await get_session(request)
    if not session.get("user"):
        # API retorna 401, browser redireciona para login
        if path.startswith("/api/"):
            return web.json_response(
                {"ok": False, "message": "Não autenticado"},
                status=401,
            )
        raise web.HTTPFound("/login")

    return await handler(request)


# ─── Routes ──────────────────────────────────────────────────

async def login_page(request):
    """Página de login com botão Google."""
    if not is_auth_configured():
        raise web.HTTPFound("/")

    session = await get_session(request)
    if session.get("user"):
        raise web.HTTPFound("/")

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login — LG TV Controller</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #1a1a2e; color: #e0e0e0; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }
        .login-card { background: #16213e; border-radius: 16px; padding: 3rem;
                      box-shadow: 0 8px 32px rgba(0,0,0,0.3); text-align: center;
                      max-width: 400px; width: 100%; }
        .login-card h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
        .login-card p { color: #888; margin-bottom: 2rem; }
        .btn-google { background: #fff; color: #333; border: none; padding: 12px 24px;
                      border-radius: 8px; font-size: 1rem; font-weight: 500;
                      display: inline-flex; align-items: center; gap: 10px;
                      text-decoration: none; transition: box-shadow 0.2s; }
        .btn-google:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.2); color: #333; }
        .btn-google img { width: 20px; height: 20px; }
        .error { color: #e74c3c; margin-top: 1rem; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>🖥️ LG TV Controller</h1>
        <p>Faça login para acessar o painel</p>
        <a href="/auth/callback?action=start" class="btn-google">
            <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="G">
            Entrar com Google
        </a>
        ERRMSG
    </div>
</body>
</html>"""

    error = request.query.get("error", "")
    error_html = f'<p class="error">{error}</p>' if error else ""
    html = html.replace("ERRMSG", error_html)
    return web.Response(text=html, content_type="text/html")


async def auth_callback(request):
    """Handles both the redirect to Google and the callback from Google."""

    if not is_auth_configured():
        raise web.HTTPFound("/")

    # Step 1: Redirect to Google
    if request.query.get("action") == "start":
        state = secrets.token_urlsafe(32)
        session = await get_session(request)
        session["oauth_state"] = state

        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        raise web.HTTPFound(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")

    # Step 2: Handle callback from Google
    code = request.query.get("code")
    state = request.query.get("state")
    error = request.query.get("error")

    if error:
        raise web.HTTPFound(f"/login?error=Google: {error}")

    if not code:
        raise web.HTTPFound("/login?error=Código de autorização ausente")

    # Validate state
    session = await get_session(request)
    expected_state = session.pop("oauth_state", None)
    if not expected_state or state != expected_state:
        raise web.HTTPFound("/login?error=Estado OAuth inválido")

    # Exchange code for token
    try:
        async with _aiohttp.ClientSession() as http:
            async with http.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Token exchange failed: {resp.status} {body}")
                    raise web.HTTPFound("/login?error=Falha ao obter token")
                token_data = await resp.json()

            # Get user info
            access_token = token_data["access_token"]
            async with http.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as resp:
                if resp.status != 200:
                    raise web.HTTPFound("/login?error=Falha ao obter perfil")
                user_info = await resp.json()

    except web.HTTPFound:
        raise
    except Exception as e:
        logger.exception("OAuth error")
        raise web.HTTPFound(f"/login?error={e}")

    email = user_info.get("email", "").lower()
    name = user_info.get("name", email)
    picture = user_info.get("picture", "")

    # Check allowed emails
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        logger.warning(f"Acesso negado para {email}")
        raise web.HTTPFound(f"/login?error=Acesso negado para {email}")

    # Save session
    session["user"] = {
        "email": email,
        "name": name,
        "picture": picture,
    }
    logger.info(f"Login: {name} ({email})")

    raise web.HTTPFound("/")


async def auth_logout(request):
    """Logout — limpa sessão."""
    session = await get_session(request)
    session.clear()
    raise web.HTTPFound("/login")


async def api_user(request):
    """Retorna dados do usuário logado."""
    session = await get_session(request)
    user = session.get("user")
    if not user:
        return web.json_response({"ok": False}, status=401)
    return web.json_response({"ok": True, "user": user})


# ─── Setup ───────────────────────────────────────────────────

def setup_auth(app: web.Application):
    """Configura autenticação no app aiohttp."""
    # Session storage (encrypted cookie) — must be set up before auth middleware
    key = SESSION_SECRET.encode()[:32].ljust(32, b"\0")
    setup_session(app, EncryptedCookieStorage(key, cookie_name="tvctrl_session", max_age=86400 * 7))

    # Auth middleware — added AFTER session middleware (setup_session appends its own)
    if is_auth_configured():
        app.middlewares.append(auth_middleware)

    # Routes
    app.router.add_get("/login", login_page)
    app.router.add_get("/auth/callback", auth_callback)
    app.router.add_get("/auth/logout", auth_logout)
    app.router.add_get("/api/user", api_user)

    if is_auth_configured():
        logger.info(f"Google OAuth ativo — emails permitidos: {ALLOWED_EMAILS or ['todos']}")
    else:
        logger.warning("GOOGLE_CLIENT_ID/SECRET não configurados — autenticação desabilitada")
