"""AES-256-GCM; vault key and per-payload key both use PBKDF2 with 600k rounds.
The session holds only a password-derived vault key, never the password.
Per-record salts derive independent keys from that vault key (a two-stage KDF).
"""
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 600_000
MAGIC = b'WN01'


def derive(secret: bytes, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(secret)


def password_key(password: str, salt: bytes) -> bytes:
    return derive(password.encode('utf-8'), salt)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    salt = os.urandom(16)
    iv = os.urandom(12)
    payload_key = derive(key, salt)
    return MAGIC + salt + iv + AESGCM(payload_key).encrypt(iv, plaintext, aad)


def decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 48 or blob[:4] != MAGIC:
        raise ValueError('Invalid encrypted payload')
    salt, iv, ciphertext = blob[4:20], blob[20:32], blob[32:]
    return AESGCM(derive(key, salt)).decrypt(iv, ciphertext, aad)
