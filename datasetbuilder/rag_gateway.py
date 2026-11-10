"""TotalCare gateway integration. Never log upstream bodies, tokens, or article content."""
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class GatewayError(Exception):
    pass


def request_operation(method, path):
    document = r'/documents/[0-9a-f-]{36}'
    operations = {
        ('POST', r'/documents'): ('uploading the document', 'documents:upload'),
        ('POST', document + r'/versions'): ('uploading a new version', 'documents:manage'),
        ('PATCH', document): ('updating document metadata', 'documents:manage'),
        ('GET', document): ('reading document metadata', 'documents:read'),
        ('GET', document + r'/permissions'): ('reading document permissions', 'documents:manage'),
        ('GET', document + r'/status'): ('checking indexing status', 'documents:read'),
    }
    for (expected_method, pattern), result in operations.items():
        if method == expected_method and re.fullmatch(pattern, path):
            return result
    return 'processing the document', None


def valid_url(value):
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment
            and len(value) <= 500)


def cipher():
    key = current_app.config.get('RAG_ENCRYPTION_KEY', '')
    try:
        return Fernet(key.encode('ascii'))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise GatewayError('Configure a valid RAG_ENCRYPTION_KEY on the server.') from exc


def encrypt_secret(secret):
    return cipher().encrypt(secret.encode('utf-8')).decode('ascii')


def decrypt_secret(secret):
    try:
        return cipher().decrypt(secret.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError) as exc:
        raise GatewayError('Cannot decrypt the gateway secret; check RAG_ENCRYPTION_KEY.') from exc


def destination(settings):
    value = json.dumps([settings.gateway_url.rstrip('/'), settings.tenant_id, settings.client_id],
                       ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Gateway:
    def __init__(self, settings):
        self.settings = settings
        self.base = settings.gateway_url.rstrip('/') + '/api/v1'
        self.session = requests.Session()
        self.session.trust_env = False
        secret = decrypt_secret(settings.secret_ciphertext)
        try:
            response = self.session.post(settings.token_url, data={
                'grant_type': 'client_credentials', 'client_id': settings.client_id,
                'client_secret': secret,
            }, timeout=(5, 20), allow_redirects=False)
        except requests.RequestException as exc:
            raise GatewayError('Could not reach the OAuth token endpoint.') from exc
        if response.status_code != 200:
            raise GatewayError(f'OAuth authentication failed (HTTP {response.status_code}).')
        try:
            token = response.json()['access_token']
            if not isinstance(token, str) or not token:
                raise ValueError('invalid token')
        except (ValueError, KeyError, TypeError) as exc:
            raise GatewayError('OAuth endpoint returned an invalid token response.') from exc
        self.headers = {'Authorization': f'Bearer {token}', 'X-Tenant-ID': settings.tenant_id}

    def request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, self.base + path, headers=self.headers,
                                            timeout=(5, 60), allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise GatewayError('Gateway connection failed; the outcome may be unknown.') from exc
        if not 200 <= response.status_code < 300:
            operation, scope = request_operation(method, path)
            message = f'Gateway request failed while {operation} (HTTP {response.status_code}).'
            if response.status_code == 403 and scope:
                message += (f' Check the selected tenant and the OAuth client’s {scope} scope; '
                            'gateway access restrictions may also apply.')
            raise GatewayError(message)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError('Gateway returned an invalid response.') from exc
        if not isinstance(payload, dict):
            raise GatewayError('Gateway returned an invalid response.')
        return payload

    @staticmethod
    def identifier(value):
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise GatewayError('Gateway returned an invalid document or version ID.') from exc

    def upload(self, doc, metadata, remote_id=None):
        files = {'file': (doc.filename, doc.markdown.encode('utf-8'), 'text/markdown')}
        if remote_id:
            return self.request('POST', f'/documents/{self.identifier(remote_id)}/versions', files=files)
        fields = {key: metadata[key] for key in ('title', 'manufacturer', 'equipment_model', 'language')}
        fields['external_totalcare_document_id'] = doc.kb_id
        return self.request('POST', '/documents', data=fields, files=files)

    def update_metadata(self, remote_id, metadata, kb_id):
        path = f'/documents/{self.identifier(remote_id)}'
        expected = {
            **metadata, 'external_totalcare_document_id': kb_id,
        }
        self.request('PATCH', path, json=expected)
        actual = self.request('GET', path)
        if any(actual.get(key) != value for key, value in expected.items()):
            raise GatewayError('Gateway did not confirm the requested document metadata.')

    def verify_permissions(self, remote_id, subjects):
        path = f'/documents/{self.identifier(remote_id)}/permissions'
        actual = self.request('GET', path).get('subjects')
        if not isinstance(actual, list) or not all(isinstance(s, str) for s in actual):
            raise GatewayError('Gateway returned invalid document permissions.')
        if not set(subjects).issubset(actual):
            raise GatewayError('Required subjects are not granted access. An administrator must grant them in the gateway.')

    def status(self, remote_id):
        return self.request('GET', f'/documents/{self.identifier(remote_id)}/status')
