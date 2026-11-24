#!/usr/bin/env python3
"""Üretim anahtarları üretir (SECRET_KEY, ENCRYPTION_KEY, parolalar). Çıktıyı .env dosyasına elle yapıştırın."""
import secrets

from cryptography.fernet import Fernet

print("SECRET_KEY=" + secrets.token_urlsafe(48))
print("ENCRYPTION_KEY=" + Fernet.generate_key().decode())
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))
print("MINIO_ROOT_PASSWORD=" + secrets.token_urlsafe(24))
