import json
import os
import time
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from app.services.crypto import LEGACY_MAGIC, MAGIC, decrypt, derive, encrypt, password_key
from app.services.deid import scan, scan_record
from app.services.store import TEST_BLOB, Vault
from app.schemas import empty_record


def legacy_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    salt, iv = os.urandom(16), os.urandom(12)
    return LEGACY_MAGIC + salt + iv + AESGCM(derive(key, salt)).encrypt(iv, plaintext, aad)


def test_identifier_patterns():
    text = 'Mr. John Reyes, email john@example.org, phone +63 917 123 4567, ID 123456789, born 2000-01-23 and January 23, 2000.'
    found = scan(text)
    assert {'Possible patient name', 'Email address', 'Phone number', 'Possible hospital / ID number', 'Full date / possible birthdate'} <= {f['kind'] for f in found}
    assert any(f['text'] == 'John Reyes' for f in found)
    assert not scan('HR 90, BP 120/80, temperature 37 C.')
    record = empty_record(); record.hpi = text
    assert all(f['field'] == 'hpi' for f in scan_record(record))


def test_roundtrip_wrong_password_and_authenticated_metadata():
    salt = os.urandom(16)
    key = password_key('a long password', salt)
    wrong = password_key('another password', salt)
    for data, aad in [(b'patient draft', b'record:1'), (b'{"text":"private chunk","embedding":[0.1,0.9]}', b'chunk:1')]:
        encrypted = encrypt(key, data, aad)
        assert encrypted.startswith(MAGIC)
        assert data not in encrypted
        assert decrypt(key, encrypted, aad) == data
        assert decrypt(key, legacy_encrypt(key, data, aad), aad) == data
        assert encrypted != encrypt(key, data, aad)
        with pytest.raises(InvalidTag): decrypt(wrong, encrypted, aad)
        with pytest.raises(InvalidTag): decrypt(key, encrypted, b'changed')


def test_vault_locked_wrong_password_and_index_rebuild(tmp_path):
    vault = Vault(tmp_path)
    token = vault.unlock('my strong password')
    vault.authorize(token)
    record = {'id': 'r1', 'timestamp': 'secret date', 'chief_complaint': 'private symptom'}
    chunk = {'id': 'c1', 'text': 'private text', 'embedding': [0.1, 0.2]}
    vault.put_many([('record', record), ('chunk', chunk)])
    key = vault.key()
    with vault.db:
        vault.db.execute("UPDATE settings SET value=? WHERE name='verifier'",
                         (legacy_encrypt(key, TEST_BLOB, b'verifier'),))
        vault.db.execute('UPDATE payloads SET data=? WHERE id=?',
                         (legacy_encrypt(key, json.dumps(record).encode(), b'record:r1'), 'r1'))
        vault.db.execute('UPDATE payloads SET data=? WHERE id=?',
                         (legacy_encrypt(key, json.dumps(chunk).encode(), b'chunk:c1'), 'c1'))
    vault.lock()
    assert not vault.index and vault._key is None
    with pytest.raises(HTTPException): vault.authorize(token)
    with pytest.raises(HTTPException): vault.unlock('wrong password')
    assert vault.token is None
    vault.unlock('my strong password')
    assert vault.get('record', 'r1')['chief_complaint'] == 'private symptom'
    assert vault.index[0]['embedding'] == [0.1, 0.2]
    assert vault.db.execute("SELECT data FROM payloads WHERE id='c1'").fetchone()[0].startswith(MAGIC)
    assert vault.db.execute("SELECT data FROM payloads WHERE id='r1'").fetchone()[0].startswith(MAGIC)
    assert vault.db.execute("SELECT value FROM settings WHERE name='verifier'").fetchone()[0].startswith(MAGIC)
    assert b'private symptom' not in vault.path.read_bytes()
    assert b'private text' not in vault.path.read_bytes()
    vault.last_activity = time.monotonic() - 301
    vault.expire()
    assert vault._key is None and not vault.index
    vault.close()
