"""AES-256-GCM with a password-derived vault key and salted payload keys.

PBKDF2 remains the intentionally expensive password boundary. Payload keys use
HKDF because their input is already a high-entropy vault key. WN01 decryption is
kept for in-place migration of existing vaults.
"""
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

ITERATIONS = 600_000
LEGACY_MAGIC = b'WN01'
MAGIC = b'WN02'


def derive(secret: bytes, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(secret)


def password_key(password: str, salt: bytes) -> bytes:
    return derive(password.encode('utf-8'), salt)


def payload_key(key: bytes, salt: bytes, aad: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b'WardNote payload key v2\0' + aad).derive(key)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    salt = os.urandom(16)
    iv = os.urandom(12)
    derived = payload_key(key, salt, aad)
    return MAGIC + salt + iv + AESGCM(derived).encrypt(iv, plaintext, aad)


def decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 48 or blob[:4] not in {LEGACY_MAGIC, MAGIC}:
        raise ValueError('Invalid encrypted payload')
    salt, iv, ciphertext = blob[4:20], blob[20:32], blob[32:]
    derived = derive(key, salt) if blob[:4] == LEGACY_MAGIC else payload_key(key, salt, aad)
    return AESGCM(derived).decrypt(iv, ciphertext, aad)


def is_legacy(blob: bytes) -> bool:
    return blob[:4] == LEGACY_MAGIC
