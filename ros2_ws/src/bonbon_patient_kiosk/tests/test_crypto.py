from __future__ import annotations

from bonbon_patient_kiosk.data.crypto import PHICipher


def test_encrypt_decrypt_roundtrip():
    cipher = PHICipher(key_hex="00" * 32)
    payload = {"full_name": "Jane Tan", "symptoms": ["cough", "fever"]}
    token = cipher.encrypt(payload)
    assert "Jane Tan" not in token
    assert cipher.decrypt(token) == payload


def test_different_keys_cannot_cross_decrypt():
    cipher_a = PHICipher(key_hex="00" * 32)
    cipher_b = PHICipher(key_hex="11" * 32)
    token = cipher_a.encrypt({"secret": "value"})
    try:
        cipher_b.decrypt(token)
        assert False, "expected decryption to fail with the wrong key"
    except Exception:
        pass
