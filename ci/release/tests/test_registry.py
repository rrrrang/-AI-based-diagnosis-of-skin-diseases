"""Read-only registry proof tests; no network request or Docker command runs."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

SPEC = importlib.util.spec_from_file_location('release_registry', Path(__file__).resolve().parents[1]/'registry.py')
registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registry)
REPO = 'docker.io/rlarns982/skinai-api'
PATH = 'rlarns982/skinai-api'
COMMIT = 'a' * 40
TAG = 'sha-' + COMMIT[:12] + '-workflow-3'
HUB = 'https://hub.docker.com/v2/namespaces/rlarns982/repositories/skinai-api'
AUTH = 'https://auth.docker.io/token?' + urllib.parse.urlencode({'service':'registry.docker.io','scope':f'repository:{PATH}:pull'})
BASE = 'https://registry-1.docker.io/v2/' + PATH
INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'


def encoded(value):
    raw = json.dumps(value, separators=(',',':')).encode()
    return raw, 'sha256:' + hashlib.sha256(raw).hexdigest()


class RegistryProofTests(unittest.TestCase):
    def fixture(self, *, index=True, platform='amd64', duplicates=False, missing_platform=False, wrong_label=False):
        config={'architecture':platform,'os':'linux','config':{'Labels':{
            'org.opencontainers.image.revision': 'b'*40 if wrong_label else COMMIT}},
            'rootfs':{'type':'layers','diff_ids':['sha256:'+'1'*64]}}
        config_raw,self.config_digest=encoded(config)
        manifest={'schemaVersion':2,'mediaType':MANIFEST,'config':{
            'mediaType':CONFIG,'digest':self.config_digest,'size':len(config_raw)},'layers':[]}
        manifest_raw,self.platform_digest=encoded(manifest)
        descriptor={'mediaType':MANIFEST,'digest':self.platform_digest,'size':len(manifest_raw),
                    'platform':{'os':'linux','architecture':'arm64' if missing_platform else 'amd64'}}
        manifests=[descriptor,{'mediaType':MANIFEST,'digest':'sha256:'+'9'*64,'size':1,
                              'platform':{'os':'unknown','architecture':'unknown'}}]
        if duplicates: manifests.append(dict(descriptor))
        top={'schemaVersion':2,'mediaType':INDEX,'manifests':manifests} if index else manifest
        top_raw,self.top_digest=encoded(top)
        self.responses={
            HUB:(encoded({'name':'skinai-api','namespace':'rlarns982','is_private':False})[0],{}),
            AUTH:(encoded({'token':'anonymous-test-token'})[0],{}),
            BASE+'/manifests/'+TAG:(top_raw,{'docker-content-digest':self.top_digest}),
            BASE+'/manifests/'+self.platform_digest:(manifest_raw,{'docker-content-digest':self.platform_digest}),
            BASE+'/blobs/'+self.config_digest:(config_raw,{}),
        }
        self.calls=[]

    def setUp(self):
        self.fixture()

    def fetch(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if url not in self.responses:
            raise AssertionError('Unexpected fake network request')
        return self.responses[url]

    def verify(self, local=None, commit=COMMIT, expected=None):
        with patch.object(registry,'_fetch',self.fetch):
            return registry.verify_public_image(REPO,TAG,local or self.top_digest,commit,expected)

    def test_public_oci_index_and_platform_and_config_hashes(self):
        result=self.verify(expected=self.top_digest)
        self.assertEqual(result,{'digest':self.top_digest,'platform_digest':self.platform_digest,
                                 'config_digest':self.config_digest,'visibility':'public'})
        self.assertNotIn('anonymous-test-token',json.dumps(result))
        self.assertTrue(any(url.endswith('/blobs/'+self.config_digest) and kwargs['blob']
                            for url,kwargs in self.calls))

    def test_legacy_config_image_id_is_accepted_for_identical_content(self):
        self.assertEqual(self.verify(local=self.config_digest)['config_digest'],self.config_digest)

    def test_single_platform_manifest_is_supported(self):
        self.fixture(index=False)
        self.assertEqual(self.verify()['digest'],self.platform_digest)

    def test_private_or_wrong_repository_is_rejected(self):
        for response in ({'name':'skinai-api','namespace':'rlarns982','is_private':True},
                         {'name':'skinai-api','namespace':'another-user','is_private':False}):
            with self.subTest(response=response):
                self.responses[HUB]=(encoded(response)[0],{})
                with self.assertRaises(registry.RegistryError): self.verify()

    def test_unrelated_local_image_is_rejected(self):
        with self.assertRaises(registry.RegistryError): self.verify(local='sha256:'+'0'*64)

    def test_tag_move_or_different_push_digest_is_rejected(self):
        with self.assertRaises(registry.RegistryError): self.verify(expected='sha256:'+'0'*64)

    def test_ambiguous_or_missing_amd64_manifest_is_rejected(self):
        for args in ({'duplicates':True},{'missing_platform':True}):
            with self.subTest(args=args):
                self.fixture(**args)
                with self.assertRaises(registry.RegistryError): self.verify()

    def test_platform_manifest_bytes_must_match_descriptor_digest(self):
        key=BASE+'/manifests/'+self.platform_digest
        raw,headers=self.responses[key]
        self.responses[key]=(raw+b' ',headers)
        with self.assertRaises(registry.RegistryError): self.verify()

    def test_digest_header_cannot_lie_about_manifest_bytes(self):
        raw,_=self.responses[BASE+'/manifests/'+TAG]
        self.responses[BASE+'/manifests/'+TAG]=(raw,{'docker-content-digest':'sha256:'+'0'*64})
        with self.assertRaises(registry.RegistryError): self.verify()

    def test_config_blob_must_match_hash_and_size(self):
        key=BASE+'/blobs/'+self.config_digest
        raw,headers=self.responses[key]
        self.responses[key]=(raw+b' ',headers)
        with self.assertRaises(registry.RegistryError): self.verify()

    def test_config_platform_and_revision_must_match(self):
        for args in ({'platform':'arm64'},{'wrong_label':True}):
            with self.subTest(args=args):
                self.fixture(**args)
                with self.assertRaises(registry.RegistryError): self.verify()

    def test_unknown_destination_and_unsafe_reference_fail_before_network(self):
        with patch.object(registry,'_fetch',side_effect=AssertionError('Network must not be called')):
            with self.assertRaises(registry.RegistryError):
                registry.get_remote_digest('docker.io/another-user/skinai-api',TAG)
            with self.assertRaises(registry.RegistryError):
                registry.get_remote_digest(REPO,'../tokens?leak=true')

    def test_only_missing_manifest_returns_none(self):
        self.responses[BASE+'/manifests/'+TAG]=None
        with patch.object(registry,'_fetch',self.fetch):
            self.assertIsNone(registry.get_remote_digest(REPO,TAG))

    def test_duplicate_registry_json_is_rejected(self):
        self.responses[AUTH]=(b'{"token":"first","token":"second"}',{})
        with self.assertRaises(registry.RegistryError): self.verify()


class TransportTests(unittest.TestCase):
    def test_401_is_not_mistaken_for_missing_tag(self):
        err=urllib.error.HTTPError('https://registry-1.docker.io/v2/x',401,'Unauthorized',{},None)
        opener=type('Opener',(),{'open':lambda self,*a,**k: (_ for _ in ()).throw(err)})()
        with patch.object(registry.urllib.request,'build_opener',return_value=opener):
            with self.assertRaisesRegex(registry.RegistryError,'HTTP 401'):
                registry._fetch('https://registry-1.docker.io/v2/x',missing=True)

    def test_404_returns_none_only_when_requested(self):
        err=urllib.error.HTTPError('https://registry-1.docker.io/v2/x',404,'Missing',{},None)
        opener=type('Opener',(),{'open':lambda self,*a,**k: (_ for _ in ()).throw(err)})()
        with patch.object(registry.urllib.request,'build_opener',return_value=opener):
            self.assertIsNone(registry._fetch('https://registry-1.docker.io/v2/x',missing=True))
            with self.assertRaises(registry.RegistryError): registry._fetch('https://registry-1.docker.io/v2/x')

    def test_cross_host_blob_redirect_strips_authorization(self):
        request=urllib.request.Request('https://registry-1.docker.io/v2/x/blobs/sha256:a',
            headers={'Authorization':'Bearer anonymous-test-token','Accept':'application/json'})
        redirected=registry._SafeRedirect(True).redirect_request(request,None,307,'',{},'https://cdn.example.test/blob?signature=x')
        self.assertIsNone(redirected.get_header('Authorization'))
        self.assertEqual(redirected.get_method(),'GET')
        with self.assertRaises(registry.RegistryError):
            registry._SafeRedirect(False).redirect_request(request,None,307,'',{},'https://cdn.example.test/blob')

    def test_insecure_or_credential_redirect_is_refused(self):
        request=urllib.request.Request('https://registry-1.docker.io/v2/x')
        for url in ('http://cdn.example.test/blob','https://user:password@cdn.example.test/blob'):
            with self.subTest(url=url), self.assertRaises(registry.RegistryError):
                registry._SafeRedirect(True).redirect_request(request,None,307,'',{},url)

    def test_response_body_limit_is_enforced(self):
        class Response(io.BytesIO):
            headers={}
        opener=type('Opener',(),{'open':lambda self,*a,**k: Response(b'12345')})()
        with patch.object(registry.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(registry.RegistryError):
                registry._fetch('https://registry-1.docker.io/v2/x',limit=4)


if __name__=='__main__':
    unittest.main(verbosity=2)