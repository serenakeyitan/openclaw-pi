#!/usr/bin/env python3
"""Inject li_at cookie directly into Chromium's SQLite Cookies database.

Uses v10 encryption (Linux default without keyring - 'peanuts' password).
"""

import hashlib
import os
import sqlite3
import struct
import sys
import time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.backends import default_backend

PROFILE_COOKIES = None  # set at runtime


def chrome_v10_encrypt(plaintext: str) -> bytes:
    """Encrypt a cookie value using Chromium's v10 scheme (Linux, no keyring)."""
    password = b"peanuts"
    salt = b"saltysalt"
    iterations = 1
    key_length = 16
    iv = b" " * 16  # 16 spaces

    key = hashlib.pbkdf2_hmac("sha1", password, salt, iterations, dklen=key_length)

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()

    return b"v10" + encrypted


def chrome_v10_decrypt(encrypted_value: bytes) -> str:
    """Decrypt a v10 cookie for verification."""
    if not encrypted_value.startswith(b"v10"):
        return "<not v10>"

    password = b"peanuts"
    salt = b"saltysalt"
    iterations = 1
    key_length = 16
    iv = b" " * 16

    key = hashlib.pbkdf2_hmac("sha1", password, salt, iterations, dklen=key_length)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_padded = decryptor.update(encrypted_value[3:]) + decryptor.finalize()

    unpadder = sym_padding.PKCS7(128).unpadder()
    decrypted = unpadder.update(decrypted_padded) + unpadder.finalize()
    return decrypted.decode("utf-8")


def chrome_epoch(unix_ts: float) -> int:
    """Convert Unix timestamp to Chrome epoch (microseconds since 1601-01-01)."""
    return int((unix_ts + 11644473600) * 1_000_000)


def inject(cookie_value: str, db_path: str):
    encrypted = chrome_v10_encrypt(cookie_value)

    # Verify encryption roundtrip
    decrypted = chrome_v10_decrypt(encrypted)
    assert decrypted == cookie_value, f"Encryption roundtrip failed: {decrypted!r} != {cookie_value!r}"
    print(f"Encryption verified (roundtrip OK, {len(encrypted)} bytes)")

    now = time.time()
    creation = chrome_epoch(now)
    # Expire in 1 year
    expires = chrome_epoch(now + 365 * 24 * 3600)
    last_access = creation
    last_update = creation

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Delete existing li_at if present
    cur.execute("DELETE FROM cookies WHERE name = 'li_at' AND host_key = '.linkedin.com'")

    # Insert the cookie
    cur.execute(
        """INSERT INTO cookies (
            creation_utc, host_key, top_frame_site_key, name, value,
            encrypted_value, path, expires_utc, is_secure, is_httponly,
            last_access_utc, has_expires, is_persistent, priority,
            samesite, source_scheme, source_port, last_update_utc,
            source_type, has_cross_site_ancestor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            creation,           # creation_utc
            ".linkedin.com",    # host_key
            "",                 # top_frame_site_key
            "li_at",            # name
            "",                 # value (empty, using encrypted_value)
            encrypted,          # encrypted_value
            "/",                # path
            expires,            # expires_utc
            1,                  # is_secure
            1,                  # is_httponly
            last_access,        # last_access_utc
            1,                  # has_expires
            1,                  # is_persistent
            1,                  # priority (MEDIUM)
            -1,                 # samesite (UNSPECIFIED)
            2,                  # source_scheme (SECURE)
            443,                # source_port
            last_update,        # last_update_utc
            0,                  # source_type
            0,                  # has_cross_site_ancestor
        ),
    )

    conn.commit()

    # Verify
    cur.execute("SELECT name, host_key, length(encrypted_value) FROM cookies WHERE name = 'li_at'")
    row = cur.fetchone()
    conn.close()

    if row:
        print(f"Injected: {row[0]} @ {row[1]} ({row[2]} bytes encrypted)")
        return True
    else:
        print("ERROR: Cookie not found after insert!")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: inject_cookie_sqlite.py <li_at_value> <cookies_db_path>")
        sys.exit(1)

    success = inject(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
