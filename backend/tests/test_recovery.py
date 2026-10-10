import base64
import json
import os
import sqlite3

import pytest
from cryptography.exceptions import InvalidTag
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import store as store_module
from app.services.crypto import (encrypt, generate_recovery_key, parse_recovery_key,
                                 password_key, unwrap_dek, wrap_dek)
from app.services.store import FORMAT_VERSION, TEST_BLOB, Vault


def _create_legacy_vault(directory, password='legacy password'):
    vault = Vault(directory)
    salt = os.urandom(16)
    key = password_key(password, salt)
    item = {'id': 'record-1', 'chief_complaint': 'Private legacy symptom'}
    with vault.db:
        vault.db.execute("INSERT INTO settings VALUES ('salt', ?)", (salt,))
        vault.db.execute("INSERT INTO settings VALUES ('verifier', ?)",
                         (encrypt(key, TEST_BLOB, b'verifier'),))
        vault.db.execute("INSERT INTO payloads VALUES (?, 'record', ?)",
                         (item['id'], encrypt(key, json.dumps(item).encode(), b'record:record-1')))
    return vault


def _expire_recovery_delay(vault):
    vault._recovery_block_until = 0
    with vault.db:
        vault._set_setting('recovery_block_until', b'0')


def test_recovery_key_checksum_detects_typing_errors():
    displayed, raw = generate_recovery_key()
    try:
        assert bytes(parse_recovery_key(displayed.lower().replace('-', ' '))) == bytes(raw)
        replacement = 'A' if displayed[-1] != 'A' else 'B'
        with pytest.raises(ValueError, match='checksum'):
            parse_recovery_key(displayed[:-1] + replacement)
    finally:
        raw[:] = b'\x00' * len(raw)


@pytest.mark.parametrize('field', ['version', 'salt', 'iv', 'ciphertext'])
def test_tampered_dek_wrapper_is_rejected(field):
    dek, material = os.urandom(32), os.urandom(32)
    value = json.loads(wrap_dek(dek, material, 'password'))
    if field == 'version':
        value[field] = 99
    else:
        decoded = bytearray(base64.b64decode(value[field]))
        decoded[0] ^= 1
        value[field] = base64.b64encode(decoded).decode('ascii')
    tampered = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
    with pytest.raises((InvalidTag, ValueError)):
        unwrap_dek(tampered, material, 'password')


def test_setup_recover_rotates_password_and_recovery_key(tmp_path):
    vault = Vault(tmp_path)
    vault.unlock('original password')
    recovery_key = vault.setup_recovery(True)
    assert recovery_key and vault.recovery_configured
    assert recovery_key.encode() not in vault.path.read_bytes()
    parsed = parse_recovery_key(recovery_key)
    try:
        assert bytes(parsed) not in vault.path.read_bytes()
    finally:
        parsed[:] = b'\x00' * len(parsed)
    vault.put_many([('record', {'id': 'r1', 'chief_complaint': 'Private symptom'})])
    content_before_recovery = vault.db.execute("SELECT data FROM payloads WHERE id='r1'").fetchone()[0]
    vault.lock()

    token, replacement = vault.recover(recovery_key, 'replacement password', True)
    assert token and replacement and replacement != recovery_key
    assert vault.db.execute("SELECT data FROM payloads WHERE id='r1'").fetchone()[0] == content_before_recovery
    assert vault.get('record', 'r1')['chief_complaint'] == 'Private symptom'
    vault.lock()
    with pytest.raises(HTTPException) as old_password:
        vault.unlock('original password')
    assert old_password.value.status_code == 401
    vault.unlock('replacement password')
    vault.lock()
    with pytest.raises(HTTPException) as old_recovery:
        vault.recover(recovery_key, 'another replacement', False)
    assert old_recovery.value.status_code == 401
    _expire_recovery_delay(vault)
    token, no_replacement = vault.recover(replacement, 'another replacement', False)
    assert token and no_replacement is None and not vault.recovery_configured
    vault.close()


def test_regenerate_requires_password_invalidates_old_key_and_keeps_content(tmp_path):
    vault = Vault(tmp_path)
    vault.unlock('current password')
    old_key = vault.setup_recovery(True)
    vault.put_many([('record', {'id': 'r1', 'chief_complaint': 'Still readable'})])
    content_before_regeneration = vault.db.execute("SELECT data FROM payloads WHERE id='r1'").fetchone()[0]
    with pytest.raises(HTTPException) as wrong:
        vault.regenerate_recovery('wrong password')
    assert wrong.value.status_code == 401
    new_key = vault.regenerate_recovery('current password')
    assert old_key != new_key
    assert vault.db.execute("SELECT data FROM payloads WHERE id='r1'").fetchone()[0] == content_before_regeneration
    assert vault.get('record', 'r1')['chief_complaint'] == 'Still readable'
    vault.lock()
    with pytest.raises(HTTPException):
        vault.recover(old_key, 'new password here', False)
    _expire_recovery_delay(vault)
    assert vault.recover(new_key, 'new password here', False)[0]
    vault.close()


def test_recovery_failures_are_rate_limited_and_persisted(tmp_path):
    vault = Vault(tmp_path)
    vault.unlock('current password')
    vault.setup_recovery(True)
    wrong_key, raw = generate_recovery_key()
    raw[:] = b'\x00' * len(raw)
    vault.lock()
    with pytest.raises(HTTPException) as failure:
        vault.recover(wrong_key, 'replacement password', False)
    assert failure.value.status_code == 401
    with pytest.raises(HTTPException) as limited:
        vault.recover(wrong_key, 'replacement password', False)
    assert limited.value.status_code == 429 and limited.value.headers['Retry-After'] == '1'
    assert vault._setting('recovery_failures') == b'1'
    _expire_recovery_delay(vault)
    with pytest.raises(HTTPException) as second_failure:
        vault.recover(wrong_key, 'replacement password', False)
    assert second_failure.value.status_code == 401
    with pytest.raises(HTTPException) as longer_limit:
        vault.recover(wrong_key, 'replacement password', False)
    assert longer_limit.value.status_code == 429 and int(longer_limit.value.headers['Retry-After']) >= 2
    assert vault._setting('recovery_failures') == b'2'
    vault.close()

    reopened = Vault(tmp_path)
    with pytest.raises(HTTPException) as persisted:
        reopened.recover(wrong_key, 'replacement password', False)
    assert persisted.value.status_code == 429
    reopened.close()


def test_legacy_migration_backs_up_and_preserves_content(tmp_path):
    vault = _create_legacy_vault(tmp_path)
    vault.unlock('legacy password')
    assert vault._setting('format_version') == FORMAT_VERSION
    assert vault._setting('salt') is None and vault._setting('verifier') is None
    assert vault.get('record', 'record-1')['chief_complaint'] == 'Private legacy symptom'
    backup_path = tmp_path / 'vault.sqlite3.pre-envelope-v1.bak'
    assert backup_path.exists()
    backup = sqlite3.connect(f'file:{backup_path}?mode=ro', uri=True)
    try:
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert backup.execute("SELECT value FROM settings WHERE name='verifier'").fetchone()
    finally:
        backup.close()
    vault.close()


def test_legacy_migration_rolls_back_after_failure(tmp_path, monkeypatch):
    vault = _create_legacy_vault(tmp_path)
    original_encrypt = store_module.encrypt

    def fail_encrypt(*args, **kwargs):
        raise RuntimeError('injected migration failure')

    monkeypatch.setattr(store_module, 'encrypt', fail_encrypt)
    with pytest.raises(RuntimeError, match='injected'):
        vault.unlock('legacy password')
    assert vault._setting('format_version') is None
    assert vault._setting('salt') is not None and vault._setting('verifier') is not None
    assert (tmp_path / 'vault.sqlite3.pre-envelope-v1.bak').exists()
    monkeypatch.setattr(store_module, 'encrypt', original_encrypt)
    vault.unlock('legacy password')
    assert vault.get('record', 'record-1')['chief_complaint'] == 'Private legacy symptom'
    vault.close()


def test_recovery_api_and_secrets_are_not_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    caplog.set_level('DEBUG')
    with TestClient(app) as client:
        created = client.post('/api/unlock', json={'password': 'private setup password'})
        assert created.status_code == 200 and created.json()['recovery_prompt'] is True
        headers = {'Authorization': 'Bearer ' + created.json()['token']}
        setup = client.post('/api/vault/recovery/setup', headers=headers, json={'enabled': True})
        recovery_key = setup.json()['recovery_key']
        assert recovery_key and client.get('/api/status').json()['recovery_configured'] is True
        assert client.post('/api/lock', headers=headers).status_code == 200
        recovered = client.post('/api/vault/recover', json={
            'recovery_key': recovery_key,
            'new_password': 'private recovered password',
            'generate_new_recovery': True,
        })
        assert recovered.status_code == 200 and recovered.json()['recovery_key'] != recovery_key
    assert recovery_key not in caplog.text
    assert 'private setup password' not in caplog.text
    assert 'private recovered password' not in caplog.text


def test_recovery_setup_can_be_declined_without_reprompting(tmp_path, monkeypatch):
    monkeypatch.setenv('WARDNOTE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        created = client.post('/api/unlock', json={'password': 'private setup password'}).json()
        headers = {'Authorization': 'Bearer ' + created['token']}
        declined = client.post('/api/vault/recovery/setup', headers=headers, json={'enabled': False})
        assert declined.status_code == 200 and declined.json()['configured'] is False
        client.post('/api/lock', headers=headers)
        reopened = client.post('/api/unlock', json={'password': 'private setup password'}).json()
        assert reopened['recovery_prompt'] is False and reopened['recovery_configured'] is False
