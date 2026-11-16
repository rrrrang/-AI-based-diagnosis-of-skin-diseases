"""Verify public Docker Hub manifests without reading local credentials.

Only anonymous, repository-scoped pull tokens are requested. They stay in memory
and are never returned or logged. This module performs GET requests only.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

REPOSITORIES = frozenset('docker.io/rlarns982/' + name for name in (
    'skinai-api', 'skinai-worker', 'skinai-patient-ui', 'skinai-doctor-ui'))
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
TAG = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')
INDEX_TYPES = frozenset({
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
})
MANIFEST_TYPES = frozenset({
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
})
CONFIG_TYPES = frozenset({
    'application/vnd.oci.image.config.v1+json',
    'application/vnd.docker.container.image.v1+json',
})
ACCEPT = ', '.join(sorted(INDEX_TYPES | MANIFEST_TYPES))
MAX_JSON_BYTES = 4 * 1024 * 1024


class RegistryError(RuntimeError):
    """A safe error message that contains no token or signed redirect URL."""


def _repository(repository):
    if repository not in REPOSITORIES:
        raise RegistryError('Repository is outside the four approved destinations')
    return repository.removeprefix('docker.io/')


def _digest(value):
    if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
        raise RegistryError('Invalid SHA-256 digest')
    return value


def _reference(value):
    if not isinstance(value, str) or not (TAG.fullmatch(value) or DIGEST.fullmatch(value)):
        raise RegistryError('Invalid image tag or digest')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError('Duplicate JSON field in registry response')
        result[key] = value
    return result


def _json(body):
    try:
        value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError) as exc:
        raise RegistryError('Registry returned invalid JSON') from None
    if not isinstance(value, dict):
        raise RegistryError('Registry JSON must be an object')
    return value


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_blob_redirect=False):
        self.allow_blob_redirect = allow_blob_redirect

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (new.scheme != 'https' or not new.hostname or new.username or new.password
                or new.port not in (None, 443)):
            raise RegistryError('Registry redirect is not an approved HTTPS destination')
        cross_host = old.hostname != new.hostname
        if cross_host and not self.allow_blob_redirect:
            raise RegistryError('Unexpected cross-host registry redirect')
        # urllib adds Host as an unredirected header before this callback.
        # Let the next request compute its own Host, including CDN redirects.
        forwarded = {name: value for name, value in req.header_items()
                     if name.lower() != 'host'
                     and not (cross_host and name.lower() in ('authorization', 'cookie', 'proxy-authorization'))}
        # Only GET is used; do not copy credentials into redirected URLs or bodies.
        return urllib.request.Request(newurl, headers=forwarded, method='GET')


def _fetch(url, *, headers=None, missing=False, limit=MAX_JSON_BYTES, blob=False):
    request = urllib.request.Request(url, headers=headers or {}, method='GET')
    opener = urllib.request.build_opener(_SafeRedirect(allow_blob_redirect=blob))
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read(limit + 1)
            metadata = {name.lower(): value for name, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and missing:
            return None
        raise RegistryError(f'Registry request failed (HTTP {exc.code})') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RegistryError('Registry request failed or timed out') from None
    if len(raw) > limit:
        raise RegistryError('Registry response exceeded the size limit')
    return raw, metadata


def get_public_repository(repository):
    """Return non-sensitive public metadata, or None for HTTP 404 only."""
    path = _repository(repository)
    namespace, name = path.split('/')
    response = _fetch(f'https://hub.docker.com/v2/namespaces/{namespace}/repositories/{name}', missing=True)
    if response is None:
        return None
    data = _json(response[0])
    if data.get('namespace') != namespace or data.get('name') != name:
        raise RegistryError('Docker Hub repository identity did not match')
    if data.get('is_private') is not False:
        raise RegistryError('Docker Hub repository is not public')
    return {'namespace': namespace, 'name': name, 'is_private': False}


class _AnonymousPull:
    def __init__(self, repository):
        self.path = _repository(repository)
        query = urllib.parse.urlencode({'service': 'registry.docker.io',
                                      'scope': f'repository:{self.path}:pull'})
        data = _json(_fetch('https://auth.docker.io/token?' + query, limit=65536)[0])
        token = data.get('token') or data.get('access_token')
        if not isinstance(token, str) or not token or len(token) > 32768 or any(c.isspace() for c in token):
            raise RegistryError('Anonymous registry authorization was not issued')
        self._headers = {'Authorization': 'Bearer ' + token, 'Accept': ACCEPT}

    def document(self, reference, *, missing=False):
        reference = _reference(reference)
        response = _fetch(f'https://registry-1.docker.io/v2/{self.path}/manifests/{reference}',
                          headers=self._headers, missing=missing)
        if response is None:
            return None
        raw, headers = response
        value = 'sha256:' + hashlib.sha256(raw).hexdigest()
        if DIGEST.fullmatch(reference) and value != reference:
            raise RegistryError('Manifest bytes did not match the requested digest')
        if headers.get('docker-content-digest') is not None and _digest(headers['docker-content-digest']) != value:
            raise RegistryError('Manifest digest header did not match its bytes')
        data = _json(raw)
        if type(data.get('schemaVersion')) is not int or data['schemaVersion'] != 2:
            raise RegistryError('Unsupported manifest schema')
        if data.get('mediaType') not in INDEX_TYPES | MANIFEST_TYPES:
            raise RegistryError('Unsupported manifest media type')
        return data, value, len(raw)

    def config(self, descriptor):
        digest, size = _descriptor(descriptor, CONFIG_TYPES)
        response = _fetch(f'https://registry-1.docker.io/v2/{self.path}/blobs/{digest}',
                          headers=self._headers, blob=True)
        raw = response[0]
        if len(raw) != size or 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
            raise RegistryError('Image config bytes did not match the descriptor')
        return _json(raw), digest


def _descriptor(value, types):
    if not isinstance(value, dict) or value.get('mediaType') not in types:
        raise RegistryError('Unsupported image descriptor')
    digest = _digest(value.get('digest'))
    if type(value.get('size')) is not int or not 0 < value['size'] <= MAX_JSON_BYTES:
        raise RegistryError('Invalid image descriptor size')
    return digest, value['size']


def get_remote_digest(repository, tag):
    """Return the anonymous registry manifest digest; only HTTP 404 means absent."""
    _reference(tag)
    value = _AnonymousPull(repository).document(tag, missing=True)
    return None if value is None else value[1]


def verify_public_image(repository, tag, local_image_id, commit, expected_digest=None):
    """Prove anonymous access, content hashes, linux/amd64 and tested image identity."""
    _reference(tag)
    _digest(local_image_id)
    if not isinstance(commit, str) or COMMIT.fullmatch(commit) is None:
        raise RegistryError('Invalid source commit')
    if expected_digest is not None:
        _digest(expected_digest)
    if get_public_repository(repository) is None:
        raise RegistryError('Public Docker Hub repository was not found')
    client = _AnonymousPull(repository)
    top, top_digest, _ = client.document(tag)
    if expected_digest is not None and expected_digest != top_digest:
        raise RegistryError('Published digest did not match the observed registry tag')
    if top['mediaType'] in INDEX_TYPES:
        entries = top.get('manifests')
        if not isinstance(entries, list):
            raise RegistryError('Image index is missing manifest descriptors')
        choices = [entry for entry in entries if isinstance(entry, dict)
                   and isinstance(entry.get('platform'), dict)
                   and entry['platform'].get('os') == 'linux'
                   and entry['platform'].get('architecture') == 'amd64'
                   and entry['platform'].get('variant') in (None, '')]
        if len(choices) != 1:
            raise RegistryError('Expected exactly one linux/amd64 platform manifest')
        platform_digest, size = _descriptor(choices[0], MANIFEST_TYPES)
        manifest, observed_digest, observed_size = client.document(platform_digest)
        if observed_digest != platform_digest or observed_size != size or manifest['mediaType'] not in MANIFEST_TYPES:
            raise RegistryError('Platform manifest did not match its descriptor')
    else:
        manifest, platform_digest = top, top_digest
    config, config_digest = client.config(manifest.get('config'))
    if config.get('os') != 'linux' or config.get('architecture') != 'amd64':
        raise RegistryError('Image config platform did not match linux/amd64')
    labels = config.get('config', {}).get('Labels', {})
    if not isinstance(labels, dict) or labels.get('org.opencontainers.image.revision') != commit:
        raise RegistryError('Image source revision label did not match')
    if local_image_id not in {top_digest, platform_digest, config_digest}:
        raise RegistryError('Remote image does not match the tested local image')
    return {'digest': top_digest, 'platform_digest': platform_digest,
            'config_digest': config_digest, 'visibility': 'public'}