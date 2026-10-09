import json
import os
import secrets
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from app.services.crypto import password_key, encrypt, decrypt, is_legacy

TEST_BLOB = b'WardNote local vault verifier v1'


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

    @property
    def initialized(self) -> bool:
        return self.db.execute("SELECT 1 FROM settings WHERE name='salt'").fetchone() is not None

    def lock(self):
        with self.mutex:
            if self._key is not None:
                self._key[:] = b'\x00' * len(self._key)
            self._key = None
            self.token = None
            self.index.clear()

    def expire(self):
        if self._key is not None and time.monotonic() - self.last_activity >= self.auto_lock_minutes * 60:
            self.lock()

    def unlock(self, password: str) -> str:
        with self.mutex:
            self.lock()
            if not self.initialized:
                if len(password) < 10:
                    raise HTTPException(422, 'Choose a password of at least 10 characters. It cannot be recovered if lost.')
                salt = os.urandom(16)
                key = password_key(password, salt)
                verifier = encrypt(key, TEST_BLOB, b'verifier')
                with self.db:
                    self.db.execute("INSERT INTO settings VALUES ('salt', ?)", (salt,))
                    self.db.execute("INSERT INTO settings VALUES ('verifier', ?)", (verifier,))
            else:
                salt = self.db.execute("SELECT value FROM settings WHERE name='salt'").fetchone()[0]
                key = password_key(password, salt)
                verifier = self.db.execute("SELECT value FROM settings WHERE name='verifier'").fetchone()[0]
                try:
                    if decrypt(key, verifier, b'verifier') != TEST_BLOB:
                        raise InvalidTag()
                except (InvalidTag, ValueError):
                    raise HTTPException(401, 'Wrong password. The vault remains locked.') from None
                if is_legacy(verifier):
                    with self.db:
                        self.db.execute("UPDATE settings SET value=? WHERE name='verifier'",
                                        (encrypt(key, TEST_BLOB, b'verifier'),))
            self._key = bytearray(key)
            self.token = secrets.token_urlsafe(32)
            self.last_activity = time.monotonic()
            try:
                self.index = self._load_bucket('chunk', key, parallel_legacy=True)
            except (InvalidTag, ValueError):
                self.lock()
                raise HTTPException(500, 'Encrypted library is damaged or has been altered. Restore a trusted backup.') from None
            self.last_activity = time.monotonic()
            return self.token

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
