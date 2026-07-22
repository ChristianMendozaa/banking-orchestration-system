import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.errors import AppError

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(subject: str, role: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError("INVALID_TOKEN", "Token invalido o vencido", 401) from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise AppError("INVALID_TOKEN", "Token de acceso invalido", 401)
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_identifier(identifier: str, settings: Settings) -> str:
    normalized = "".join(identifier.upper().split())
    return hmac.new(
        settings.identifier_pepper.get_secret_value().encode(),
        normalized.encode(),
        hashlib.sha256,
    ).hexdigest()


def mask_identifier(identifier: str) -> str:
    normalized = "".join(identifier.split())
    suffix = normalized[-4:] if len(normalized) >= 4 else normalized[-1:]
    return f"****{suffix}"


def encrypt_identifier(identifier: str, case_id: str, settings: Settings) -> tuple[str, str, str]:
    key_id = settings.identifier_active_key_id
    key = base64.b64decode(settings.identifier_encryption_keys[key_id])
    nonce = secrets.token_bytes(12)
    normalized = "".join(identifier.upper().split()).encode()
    ciphertext = AESGCM(key).encrypt(nonce, normalized, case_id.encode())
    return (
        base64.b64encode(ciphertext).decode(),
        base64.b64encode(nonce).decode(),
        key_id,
    )


def decrypt_identifier(
    ciphertext: str,
    nonce: str,
    key_id: str,
    case_id: str,
    settings: Settings,
) -> str:
    encoded_key = settings.identifier_encryption_keys.get(key_id)
    if not encoded_key:
        raise AppError(
            "IDENTIFIER_KEY_UNAVAILABLE",
            "La clave del identificador no esta disponible",
            409,
        )
    try:
        return (
            AESGCM(base64.b64decode(encoded_key))
            .decrypt(
                base64.b64decode(nonce),
                base64.b64decode(ciphertext),
                case_id.encode(),
            )
            .decode()
        )
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise AppError("IDENTIFIER_DECRYPTION_FAILED", "No fue posible revelar el CI", 409) from exc
