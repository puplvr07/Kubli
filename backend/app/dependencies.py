from fastapi import Request, HTTPException


def unlocked(request: Request):
    authorization = request.headers.get('authorization', '')
    token = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else None
    vault = request.app.state.vault
    vault.authorize(token)
    return vault


def reauthorize(vault, token: str | None):
    """Reject results from a request whose vault was locked during local inference."""
    vault.authorize(token)
