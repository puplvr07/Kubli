"""AES-256-GCM envelope encryption and salted per-payload keys.

PBKDF2 remains the intentionally expensive password boundary. Distinct HKDF
labels derive password/recovery wrapping keys from their input material. Payload
keys use HKDF because their input is the random high-entropy DEK. WN01 decryption
is kept for in-place migration of existing vaults.
"""
import os
import base64
import hashlib
import json
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

ITERATIONS = 600_000
LEGACY_MAGIC = b'WN01'
MAGIC = b'WN02'
WRAPPER_VERSION = 1
PASSWORD_KEK_INFO = b'kubli-kek-password-v1'
RECOVERY_KEK_INFO = b'kubli-kek-recovery-v1'
RECOVERY_CHECKSUM_LABEL = b'kubli-recovery-checksum-v1\0'


def derive(secret: bytes, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(secret)


def password_key(password: str, salt: bytes) -> bytes:
    return derive(password.encode('utf-8'), salt)


def generate_recovery_key() -> tuple[str, bytearray]:
    raw = bytearray(secrets.token_bytes(32))
    checksum = hashlib.sha256(RECOVERY_CHECKSUM_LABEL + bytes(raw)).digest()[:3]
    encoded = base64.b32encode(bytes(raw) + checksum).decode('ascii').rstrip('=')
    return '-'.join(encoded[index:index + 4] for index in range(0, len(encoded), 4)), raw


def parse_recovery_key(value: str) -> bytearray:
    compact = ''.join(character for character in value.upper() if character != '-' and not character.isspace())
    if len(compact) != 56 or any(character not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567' for character in compact):
        raise ValueError('Recovery key format is invalid.')
    try:
        decoded = base64.b32decode(compact, casefold=True)
    except ValueError:
        raise ValueError('Recovery key format is invalid.') from None
    raw, checksum = decoded[:32], decoded[32:]
    expected = hashlib.sha256(RECOVERY_CHECKSUM_LABEL + raw).digest()[:3]
    if len(decoded) != 35 or not secrets.compare_digest(checksum, expected):
        raise ValueError('Recovery key checksum is invalid.')
    return bytearray(raw)


def _wrapper_key(material: bytes, salt: bytes, path: str) -> bytes:
    info = PASSWORD_KEK_INFO if path == 'password' else RECOVERY_KEK_INFO if path == 'recovery' else None
    if info is None:
        raise ValueError('Invalid key wrapper path.')
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(material)


def wrap_dek(dek: bytes, material: bytes, path: str) -> bytes:
    if len(dek) != 32:
        raise ValueError('Invalid data-encryption key.')
    salt, iv = os.urandom(16), os.urandom(12)
    aad = f'kubli-dek-wrapper-v{WRAPPER_VERSION}:{path}'.encode()
    ciphertext = AESGCM(_wrapper_key(material, salt, path)).encrypt(iv, dek, aad)
    return json.dumps({
        'version': WRAPPER_VERSION,
        'path': path,
        'salt': base64.b64encode(salt).decode('ascii'),
        'iv': base64.b64encode(iv).decode('ascii'),
        'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
    }, sort_keys=True, separators=(',', ':')).encode('ascii')


def unwrap_dek(wrapper: bytes, material: bytes, expected_path: str) -> bytes:
    try:
        value = json.loads(wrapper)
        if set(value) != {'version', 'path', 'salt', 'iv', 'ciphertext'}:
            raise ValueError()
        if value['version'] != WRAPPER_VERSION or value['path'] != expected_path:
            raise ValueError()
        salt = base64.b64decode(value['salt'], validate=True)
        iv = base64.b64decode(value['iv'], validate=True)
        ciphertext = base64.b64decode(value['ciphertext'], validate=True)
        if len(salt) != 16 or len(iv) != 12 or len(ciphertext) != 48:
            raise ValueError()
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('Invalid key wrapper.') from None
    aad = f'kubli-dek-wrapper-v{WRAPPER_VERSION}:{expected_path}'.encode()
    return AESGCM(_wrapper_key(material, salt, expected_path)).decrypt(iv, ciphertext, aad)


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
