"""Extract Google Chrome session cookies for MyGreenhouse on Windows using DPAPI and AES-GCM (ctypes)."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.ULONG),
        ("dwInfoVersion", ctypes.wintypes.ULONG),
        ("pbNonce", ctypes.c_void_p),
        ("cbNonce", ctypes.wintypes.ULONG),
        ("pbAuthData", ctypes.c_void_p),
        ("cbAuthData", ctypes.wintypes.ULONG),
        ("pbTag", ctypes.c_void_p),
        ("cbTag", ctypes.wintypes.ULONG),
        ("pbMacContext", ctypes.c_void_p),
        ("cbMacContext", ctypes.wintypes.ULONG),
        ("cbAAD", ctypes.wintypes.ULONG),
        ("cbData", ctypes.c_ulonglong),
        ("dwFlags", ctypes.wintypes.ULONG),
    ]


def _dpapi_decrypt(encrypted_data: bytes) -> bytes:
    """Decrypt DPAPI-protected bytes using Windows CryptUnprotectData."""
    if not sys.platform.startswith("win"):
        raise OSError("DPAPI decryption is only supported on Windows")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    data_in = DATA_BLOB(len(encrypted_data), ctypes.cast(encrypted_data, ctypes.POINTER(ctypes.c_byte)))
    data_out = DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(data_out),
    ):
        raise OSError(f"CryptUnprotectData failed with error code: {ctypes.GetLastError()}")

    try:
        decrypted = ctypes.string_at(data_out.pbData, data_out.cbData)
        return decrypted
    finally:
        kernel32.LocalFree(data_out.pbData)


def _bcrypt_aes_gcm_decrypt(ciphertext: bytes, key: bytes, nonce: bytes, tag: bytes) -> bytes:
    """Decrypt AES-256-GCM using Windows BCrypt API via ctypes."""
    if not sys.platform.startswith("win"):
        raise OSError("BCrypt is only supported on Windows")

    bcrypt = ctypes.windll.bcrypt

    BCRYPT_AES_ALGORITHM = ctypes.c_wchar_p("AES")
    BCRYPT_CHAINING_MODE = ctypes.c_wchar_p("ChainingMode")
    BCRYPT_CHAIN_MODE_GCM = ctypes.c_wchar_p("ChainingModeGCM")
    BCRYPT_AUTH_MODE_INFO_VERSION = 1

    h_alg = ctypes.c_void_p()
    h_key = ctypes.c_void_p()

    status = bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(h_alg), BCRYPT_AES_ALGORITHM, None, 0)
    if status != 0:
        raise OSError(f"BCryptOpenAlgorithmProvider failed: status 0x{status:X}")

    try:
        status = bcrypt.BCryptSetProperty(
            h_alg,
            BCRYPT_CHAINING_MODE,
            ctypes.cast(BCRYPT_CHAIN_MODE_GCM, ctypes.c_void_p),
            ctypes.sizeof(ctypes.c_wchar_p),
            0,
        )
        if status != 0:
            raise OSError(f"BCryptSetProperty failed: status 0x{status:X}")

        key_buf = (ctypes.c_ubyte * len(key))(*key)
        status = bcrypt.BCryptGenerateSymmetricKey(
            h_alg,
            ctypes.byref(h_key),
            None,
            0,
            key_buf,
            len(key),
            0,
        )
        if status != 0:
            raise OSError(f"BCryptGenerateSymmetricKey failed: status 0x{status:X}")

        try:
            nonce_buf = (ctypes.c_ubyte * len(nonce))(*nonce)
            tag_buf = (ctypes.c_ubyte * len(tag))(*tag)

            auth_info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
            auth_info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
            auth_info.dwInfoVersion = BCRYPT_AUTH_MODE_INFO_VERSION
            auth_info.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
            auth_info.cbNonce = len(nonce)
            auth_info.pbTag = ctypes.cast(tag_buf, ctypes.c_void_p)
            auth_info.cbTag = len(tag)

            cipher_buf = (ctypes.c_ubyte * len(ciphertext))(*ciphertext)
            plain_buf = (ctypes.c_ubyte * len(ciphertext))()
            bytes_decrypted = ctypes.wintypes.ULONG(0)

            status = bcrypt.BCryptDecrypt(
                h_key,
                cipher_buf,
                len(ciphertext),
                ctypes.byref(auth_info),
                None,
                0,
                plain_buf,
                len(ciphertext),
                ctypes.byref(bytes_decrypted),
                0,
            )
            if status != 0:
                raise OSError(f"BCryptDecrypt failed: status 0x{status:X}")

            return bytes(plain_buf[: bytes_decrypted.value])
        finally:
            bcrypt.BCryptDestroyKey(h_key)
    finally:
        bcrypt.BCryptCloseAlgorithmProvider(h_alg, 0)


def decrypt_aes_gcm(ciphertext: bytes, key: bytes, nonce: bytes, tag: bytes) -> bytes:
    """Decrypt AES-GCM with optional fallback to cryptography package if available."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext + tag, None)
    except ImportError:
        pass
    return _bcrypt_aes_gcm_decrypt(ciphertext, key, nonce, tag)


def get_chrome_user_data_dir() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    path = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    return path if path.is_dir() else None


def get_chrome_master_key(user_data_dir: Path | None = None) -> bytes | None:
    base_dir = user_data_dir or get_chrome_user_data_dir()
    if not base_dir:
        return None
    local_state_path = base_dir / "Local State"
    if not local_state_path.is_file():
        return None

    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        encrypted_key_b64 = data.get("os_crypt", {}).get("encrypted_key")
        if not encrypted_key_b64:
            return None
        encrypted_key = base64.b64decode(encrypted_key_b64)
        if not encrypted_key.startswith(b"DPAPI"):
            return None
        # Remove 'DPAPI' prefix (5 bytes)
        raw_key = encrypted_key[5:]
        return _dpapi_decrypt(raw_key)
    except Exception:
        return None


def decrypt_cookie_value(encrypted_val: bytes, master_key: bytes | None) -> str:
    if not encrypted_val:
        return ""
    if encrypted_val.startswith(b"v10") or encrypted_val.startswith(b"v11"):
        if not master_key:
            return ""
        nonce = encrypted_val[3:15]
        ciphertext_and_tag = encrypted_val[15:]
        if len(ciphertext_and_tag) < 16:
            return ""
        ciphertext = ciphertext_and_tag[:-16]
        tag = ciphertext_and_tag[-16:]
        try:
            plain = decrypt_aes_gcm(ciphertext, master_key, nonce, tag)
            return plain.decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        plain = _dpapi_decrypt(encrypted_val)
        return plain.decode("utf-8", errors="replace")
    except Exception:
        return ""


def get_chrome_cookie_db_path(profile: str = "Default", user_data_dir: Path | None = None) -> Path | None:
    base_dir = user_data_dir or get_chrome_user_data_dir()
    if not base_dir:
        return None

    profile_dir = base_dir / profile
    network_cookies = profile_dir / "Network" / "Cookies"
    if network_cookies.is_file():
        return network_cookies
    legacy_cookies = profile_dir / "Cookies"
    if legacy_cookies.is_file():
        return legacy_cookies
    return None


def extract_greenhouse_cookies(
    profile: str = "Default",
    user_data_dir: Path | None = None,
    domain_substring: str = "greenhouse.io",
) -> dict[str, str]:
    """Extract cookies matching domain_substring from Chrome's SQLite database safely."""
    db_path = get_chrome_cookie_db_path(profile, user_data_dir)
    if not db_path:
        return {}

    master_key = get_chrome_master_key(user_data_dir)

    cookies: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "Cookies.tmp"
        try:
            shutil.copy2(db_path, temp_db)
            wal_file = db_path.parent / (db_path.name + "-wal")
            if wal_file.is_file():
                shutil.copy2(wal_file, Path(tmpdir) / (temp_db.name + "-wal"))
        except OSError:
            return {}

        try:
            conn = sqlite3.connect(str(temp_db))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (f"%{domain_substring}%",),
            )
            rows = cursor.fetchall()
            for name, val, enc_val in rows:
                if val:
                    cookies[name] = val
                elif enc_val:
                    decrypted = decrypt_cookie_value(enc_val, master_key)
                    if decrypted:
                        cookies[name] = decrypted
            conn.close()
        except sqlite3.Error:
            return {}

    return cookies


def get_my_greenhouse_session_cookie(
    profile: str = "Default",
    user_data_dir: Path | None = None,
) -> str | None:
    """Retrieve _session_id (or _my_greenhouse_session) cookie or combined cookie string."""
    cookies = extract_greenhouse_cookies(profile=profile, user_data_dir=user_data_dir)
    session = cookies.get("_session_id") or cookies.get("_my_greenhouse_session")
    if session:
        return f"_session_id={session}"
    if cookies:
        return "; ".join(f"{k}={v}" for k, v in cookies.items())
    return None
