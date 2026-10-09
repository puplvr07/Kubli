import os
import time
import pytest
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from app.services.crypto import encrypt, decrypt, password_key
from app.services.deid import scan, scan_record
from app.services.store import Vault
from app.schemas import empty_record


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
        assert data not in encrypted
        assert decrypt(key, encrypted, aad) == data
        assert encrypted != encrypt(key, data, aad)
        with pytest.raises(InvalidTag): decrypt(wrong, encrypted, aad)
        with pytest.raises(InvalidTag): decrypt(key, encrypted, b'changed')


def test_vault_locked_wrong_password_and_index_rebuild(tmp_path):
    vault = Vault(tmp_path)
    token = vault.unlock('my strong password')
    vault.authorize(token)
    vault.put_many([('record', {'id': 'r1', 'timestamp': 'secret date', 'chief_complaint': 'private symptom'}), ('chunk', {'id': 'c1', 'text': 'private text', 'embedding': [0.1, 0.2]})])
    vault.lock()
    assert not vault.index and vault._key is None
    with pytest.raises(HTTPException): vault.authorize(token)
    with pytest.raises(HTTPException): vault.unlock('wrong password')
    assert vault.token is None
    vault.unlock('my strong password')
    assert vault.get('record', 'r1')['chief_complaint'] == 'private symptom'
    assert vault.index[0]['embedding'] == [0.1, 0.2]
    assert b'private symptom' not in vault.path.read_bytes()
    assert b'private text' not in vault.path.read_bytes()
    vault.last_activity = time.monotonic() - 301
    vault.expire()
    assert vault._key is None and not vault.index
    vault.close()
