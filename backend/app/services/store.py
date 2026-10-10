from __future__ import annotations

import json
import math
import os
import secrets
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cryptography.exceptions import InvalidTag
from fastapi import HTTPException

from app.services.crypto import (
    decrypt,
    encrypt,
    generate_recovery_key,
    is_legacy,
    parse_recovery_key,
    password_key,
    unwrap_dek,
    wrap_dek,
)

TEST_BLOB = b'WardNote local vault verifier v1'
FORMAT_VERSION = b'2'
MIN_PASSWORD_LENGTH = 12


def _zero(value: bytearray | None):
    if value is not None:
        value[:] = b'\x00' * len(value)


class Vault:
    def __init__(self, directory: Path, auto_lock_minutes: float = 5):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / 'vault.sqlite3'
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value BLOB NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS payloads (id TEXT PRIMARY KEY, bucket TEXT NOT NULL, data BLOB NOT NULL)')
        self.db.commit()
        os.chmod(self.path, 0o600)
        self._key: bytearray | None = None
        self.token: str | None = None
        self.last_activity = 0.0
        self.auto_lock_minutes = auto_lock_minutes
        self.mutex = threading.RLock()
        self.index: list[dict] = []
        self.last_unlock_created = False
        self._recovery_block_until = 0.0

    def _setting(self, name: str) -> bytes | None:
        row = self.db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
        return row[0] if row else None

    def _set_setting(self, name: str, value: bytes):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (name, value))

    @property
    def initialized(self) -> bool:
        return self._setting('format_version') is not None or self._setting('salt') is not None

    @property
    def recovery_configured(self) -> bool:
        return self._setting('recovery_wrapper') is not None

    @property
    def recovery_prompt(self) -> bool:
        return not self.recovery_configured and self._setting('recovery_declined') != b'1'

    def lock(self):
        with self.mutex:
            _zero(self._key)
            self._key = None
            self.token = None
            self.index.clear()

    def expire(self):
        if self._key is not None and time.monotonic() - self.last_activity >= self.auto_lock_minutes * 60:
            self.lock()

    @staticmethod
    def _validate_new_password(password: str):
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(422, f'Choose a password or passphrase of at least {MIN_PASSWORD_LENGTH} characters.')

    def _create_vault(self, password: str) -> bytes:
        self._validate_new_password(password)
        dek = bytearray(secrets.token_bytes(32))
        password_material = None
        try:
            salt = os.urandom(16)
            password_material = bytearray(password_key(password, salt))
            wrapper = wrap_dek(bytes(dek), bytes(password_material), 'password')
            with self.db:
                self._set_setting('format_version', FORMAT_VERSION)
                self._set_setting('password_salt', salt)
                self._set_setting('password_wrapper', wrapper)
                self._set_setting('recovery_declined', b'0')
            return bytes(dek)
        finally:
            _zero(password_material)
            _zero(dek)

    def _password_dek(self, password: str) -> bytes:
        salt = self._setting('password_salt')
        wrapper = self._setting('password_wrapper')
        if salt is None or len(salt) != 16 or wrapper is None:
            raise HTTPException(500, 'Vault key settings are damaged or incomplete.')
        material = bytearray(password_key(password, salt))
        try:
            return unwrap_dek(wrapper, bytes(material), 'password')
        except (InvalidTag, ValueError):
            raise HTTPException(401, 'Wrong password. The vault remains locked.') from None
        finally:
            _zero(material)

    def _migration_backup(self, legacy_key: bytes) -> Path:
        backup_path = self.path.with_name(self.path.name + '.pre-envelope-v1.bak')
        if not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                self.db.backup(backup)
                result = backup.execute('PRAGMA integrity_check').fetchone()
                if not result or result[0] != 'ok':
                    raise RuntimeError('Migration backup integrity check failed.')
            finally:
                backup.close()
            os.chmod(backup_path, 0o600)
        else:
            backup = sqlite3.connect(f'file:{backup_path}?mode=ro', uri=True)
            try:
                result = backup.execute('PRAGMA integrity_check').fetchone()
                if not result or result[0] != 'ok':
                    raise RuntimeError('Existing migration backup is damaged.')
            finally:
                backup.close()
        backup = sqlite3.connect(f'file:{backup_path}?mode=ro', uri=True)
        try:
            salt_row = backup.execute("SELECT value FROM settings WHERE name='salt'").fetchone()
            verifier_row = backup.execute("SELECT value FROM settings WHERE name='verifier'").fetchone()
            if salt_row is None or verifier_row is None or decrypt(legacy_key, verifier_row[0], b'verifier') != TEST_BLOB:
                raise RuntimeError('Migration backup cannot be authenticated.')
            for item_id, bucket, blob in backup.execute('SELECT id, bucket, data FROM payloads'):
                decrypt(legacy_key, blob, f'{bucket}:{item_id}'.encode())
        except (InvalidTag, ValueError):
            raise RuntimeError('Migration backup content cannot be decrypted.') from None
        finally:
            backup.close()
        return backup_path

    def _migrate_legacy_vault(self, password: str) -> bytes:
        salt = self._setting('salt')
        verifier = self._setting('verifier')
        if salt is None or verifier is None:
            raise HTTPException(500, 'Legacy vault settings are damaged or incomplete.')
        old_key = bytearray(password_key(password, salt))
        dek = None
        try:
            try:
                if decrypt(bytes(old_key), verifier, b'verifier') != TEST_BLOB:
                    raise InvalidTag()
            except (InvalidTag, ValueError):
                raise HTTPException(401, 'Wrong password. The vault remains locked.') from None

            rows = self.db.execute('SELECT id, bucket, data FROM payloads').fetchall()
            plaintext_rows = []
            try:
                for item_id, bucket, blob in rows:
                    plaintext_rows.append((item_id, bucket, decrypt(
                        bytes(old_key), blob, f'{bucket}:{item_id}'.encode())))
            except (InvalidTag, ValueError):
                raise HTTPException(500, 'Legacy vault content is damaged or has been altered.') from None

            self._migration_backup(bytes(old_key))
            dek = bytearray(secrets.token_bytes(32))
            new_salt = os.urandom(16)
            material = bytearray(password_key(password, new_salt))
            try:
                wrapper = wrap_dek(bytes(dek), bytes(material), 'password')
            finally:
                _zero(material)
            encrypted_rows = [(encrypt(bytes(dek), plaintext, f'{bucket}:{item_id}'.encode()), item_id, bucket)
                              for item_id, bucket, plaintext in plaintext_rows]
            with self.db:
                self.db.executemany('UPDATE payloads SET data=? WHERE id=? AND bucket=?', encrypted_rows)
                self.db.execute('DELETE FROM settings')
                self._set_setting('format_version', FORMAT_VERSION)
                self._set_setting('password_salt', new_salt)
                self._set_setting('password_wrapper', wrapper)
                self._set_setting('recovery_declined', b'0')
            return bytes(dek)
        finally:
            _zero(old_key)
            _zero(dek)

    def unlock(self, password: str) -> str:
        with self.mutex:
            self.lock()
            self.last_unlock_created = not self.initialized
            if self.last_unlock_created:
                key = self._create_vault(password)
            else:
                version = self._setting('format_version')
                if version is None:
                    key = self._migrate_legacy_vault(password)
                elif version != FORMAT_VERSION:
                    raise HTTPException(500, 'This vault format is not supported by this version of TIBOQ.')
                else:
                    key = self._password_dek(password)
            self._open_with_key(key)
            return self.token or ''

    def _open_with_key(self, key: bytes):
        self._key = bytearray(key)
        self.token = secrets.token_urlsafe(32)
        self.last_activity = time.monotonic()
        try:
            self.index = self._load_bucket('chunk', key, parallel_legacy=True)
        except (InvalidTag, ValueError):
            self.lock()
            raise HTTPException(500, 'Encrypted library is damaged or has been altered. Restore a trusted backup.') from None
        self.last_activity = time.monotonic()

    def authorize(self, token: str | None, touch: bool = True):
        with self.mutex:
            self.expire()
            if not self.token or not token or not secrets.compare_digest(self.token, token):
                raise HTTPException(401, 'Vault is locked. Unlock it to continue.')
            if touch:
                self.last_activity = time.monotonic()

    def key(self) -> bytes:
        self.expire()
        if self._key is None:
            raise HTTPException(401, 'Vault is locked. Unlock it to continue.')
        return bytes(self._key)

    def setup_recovery(self, enabled: bool) -> str | None:
        with self.mutex:
            if enabled and self.recovery_configured:
                raise HTTPException(409, 'A recovery key already exists. Regenerate it from Settings instead.')
            if not enabled:
                with self.db:
                    self.db.execute("DELETE FROM settings WHERE name='recovery_wrapper'")
                    self._set_setting('recovery_declined', b'1')
                return None
            return self._replace_recovery_wrapper()

    def _replace_recovery_wrapper(self) -> str:
        recovery_key, raw = generate_recovery_key()
        try:
            wrapper = wrap_dek(self.key(), bytes(raw), 'recovery')
            with self.db:
                self._set_setting('recovery_wrapper', wrapper)
                self._set_setting('recovery_declined', b'0')
            return recovery_key
        finally:
            _zero(raw)

    def _verify_current_password(self, password: str):
        candidate = bytearray(self._password_dek(password))
        try:
            if not secrets.compare_digest(bytes(candidate), self.key()):
                raise HTTPException(401, 'Wrong password. Recovery key was not changed.')
        finally:
            _zero(candidate)

    def regenerate_recovery(self, current_password: str) -> str:
        with self.mutex:
            if not self.recovery_configured:
                raise HTTPException(409, 'No recovery key exists. Create one instead.')
            try:
                self._verify_current_password(current_password)
            except HTTPException as exc:
                if exc.status_code == 401:
                    raise HTTPException(401, 'Wrong password. Recovery key was not changed.') from None
                raise
            return self._replace_recovery_wrapper()

    def _recovery_failure_values(self) -> tuple[int, float]:
        try:
            failures = int((self._setting('recovery_failures') or b'0').decode('ascii'))
            blocked_until = float((self._setting('recovery_block_until') or b'0').decode('ascii'))
            return max(0, failures), max(0.0, blocked_until)
        except (UnicodeDecodeError, ValueError):
            return 0, 0.0

    def _check_recovery_rate_limit(self):
        _, persisted_until = self._recovery_failure_values()
        remaining = max(self._recovery_block_until - time.monotonic(), persisted_until - time.time())
        if remaining > 0:
            seconds = max(1, math.ceil(remaining))
            raise HTTPException(429, f'Too many failed recovery attempts. Try again in {seconds} seconds.',
                                headers={'Retry-After': str(seconds)})

    def _record_recovery_failure(self):
        failures, _ = self._recovery_failure_values()
        failures += 1
        delay = min(2 ** (failures - 1), 60)
        self._recovery_block_until = time.monotonic() + delay
        with self.db:
            self._set_setting('recovery_failures', str(failures).encode('ascii'))
            self._set_setting('recovery_block_until', repr(time.time() + delay).encode('ascii'))

    def recover(self, recovery_key: str, new_password: str, generate_new_recovery: bool) -> tuple[str, str | None]:
        with self.mutex:
            self.lock()
            self._validate_new_password(new_password)
            if self._setting('format_version') != FORMAT_VERSION or not self.recovery_configured:
                raise HTTPException(409, 'Recovery is not configured for this vault.')
            self._check_recovery_rate_limit()
            raw = None
            recovered_dek = None
            password_material = None
            new_recovery_raw = None
            try:
                try:
                    raw = parse_recovery_key(recovery_key)
                except ValueError as exc:
                    self._record_recovery_failure()
                    raise HTTPException(422, str(exc)) from None
                try:
                    recovered_dek = bytearray(unwrap_dek(
                        self._setting('recovery_wrapper') or b'', bytes(raw), 'recovery'))
                except (InvalidTag, ValueError):
                    self._record_recovery_failure()
                    raise HTTPException(401, 'Recovery key is incorrect. The vault remains locked.') from None

                new_salt = os.urandom(16)
                password_material = bytearray(password_key(new_password, new_salt))
                password_wrapper = wrap_dek(bytes(recovered_dek), bytes(password_material), 'password')
                replacement_key = None
                recovery_wrapper = None
                if generate_new_recovery:
                    replacement_key, new_recovery_raw = generate_recovery_key()
                    recovery_wrapper = wrap_dek(bytes(recovered_dek), bytes(new_recovery_raw), 'recovery')
                with self.db:
                    self._set_setting('password_salt', new_salt)
                    self._set_setting('password_wrapper', password_wrapper)
                    self.db.execute("DELETE FROM settings WHERE name='recovery_wrapper'")
                    if recovery_wrapper is not None:
                        self._set_setting('recovery_wrapper', recovery_wrapper)
                    self._set_setting('recovery_declined', b'0' if recovery_wrapper is not None else b'1')
                    self._set_setting('recovery_failures', b'0')
                    self._set_setting('recovery_block_until', b'0')
                self._recovery_block_until = 0.0
                self._open_with_key(bytes(recovered_dek))
                return self.token or '', replacement_key
            finally:
                _zero(raw)
                _zero(recovered_dek)
                _zero(password_material)
                _zero(new_recovery_raw)

    def put_many(self, bucket_items: list[tuple[str, dict]]):
        with self.mutex:
            key = self.key()
            blobs = [(item['id'], bucket, encrypt(key, json.dumps(item, ensure_ascii=False).encode(), f'{bucket}:{item["id"]}'.encode())) for bucket, item in bucket_items]
            with self.db:
                self.db.executemany('INSERT OR REPLACE INTO payloads VALUES (?, ?, ?)', blobs)

    def get(self, bucket: str, item_id: str) -> dict:
        with self.mutex:
            key = self.key()
            row = self.db.execute('SELECT data FROM payloads WHERE id=? AND bucket=?', (item_id, bucket)).fetchone()
            if row is None:
                raise HTTPException(404, 'Item not found in this local vault.')
            try:
                item, upgraded = self._decode_payload(key, bucket, item_id, row[0])
                if upgraded is not None:
                    with self.db:
                        self.db.execute('UPDATE payloads SET data=? WHERE id=? AND bucket=?',
                                        (upgraded, item_id, bucket))
                return item
            except (InvalidTag, ValueError):
                raise HTTPException(500, 'Encrypted item is damaged or has been altered.') from None

    def list(self, bucket: str) -> list[dict]:
        with self.mutex:
            return self._load_bucket(bucket, self.key())

    @staticmethod
    def _decode_payload(key: bytes, bucket: str, item_id: str, blob: bytes) -> tuple[dict, bytes | None]:
        aad = f'{bucket}:{item_id}'.encode()
        plaintext = decrypt(key, blob, aad)
        item = json.loads(plaintext)
        return item, encrypt(key, plaintext, aad) if is_legacy(blob) else None

    def _load_bucket(self, bucket: str, key: bytes, parallel_legacy: bool = False) -> list[dict]:
        rows = self.db.execute('SELECT id, data FROM payloads WHERE bucket=?', (bucket,)).fetchall()
        decode = lambda row: self._decode_payload(key, bucket, row[0], row[1])
        if parallel_legacy and len(rows) > 1 and any(is_legacy(row[1]) for row in rows):
            workers = min(4, os.cpu_count() or 1)
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='vault-upgrade') as pool:
                decoded = list(pool.map(decode, rows))
        else:
            decoded = [decode(row) for row in rows]
        upgrades = [(upgraded, row[0], bucket) for row, (_, upgraded) in zip(rows, decoded) if upgraded is not None]
        if upgrades:
            with self.db:
                self.db.executemany('UPDATE payloads SET data=? WHERE id=? AND bucket=?', upgrades)
        return [item for item, _ in decoded]

    def delete(self, bucket: str, item_id: str):
        with self.mutex:
            self.get(bucket, item_id)
            with self.db:
                self.db.execute('DELETE FROM payloads WHERE id=? AND bucket=?', (item_id, bucket))

    def delete_document(self, item_id: str):
        with self.mutex:
            self.get('document', item_id)
            chunk_ids = [chunk['id'] for chunk in self.index if chunk['document_id'] == item_id]
            with self.db:
                self.db.executemany('DELETE FROM payloads WHERE id=?', [(x,) for x in [item_id] + chunk_ids])
            self.index = [chunk for chunk in self.index if chunk['document_id'] != item_id]

    def close(self):
        self.lock()
        self.db.close()
