"""Host-selected local verifier protocol over bounded Linux command transport.

The command is trusted host code, not sandboxed here. Identity labels and hashes
bind a conversation, not evidence truth or remote authentication. No retries.
"""
import hashlib
import json
import uuid

from .context_shadow import encoded
from .review_decision import decide
from .worker_transport import CommandWorker


def _parse(raw, limit):
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise ValueError('provider JSON exceeds limit')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate provider JSON key')
            value[key] = item
        return value
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
        encoded(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('invalid provider JSON') from None


class CommandProvider:
    def __init__(self, check_id, provider_id, argv, *, cwd, env=None,
                 timeout=5, cleanup_timeout=5):
        self.check_id, self.provider_id = check_id, provider_id
        decide(dict(task_id='shape', target='shape', revision='shape', proposal_sha256='0'*64),
               {check_id: provider_id}, [])
        self.transport = CommandWorker(argv, cwd=cwd, env=env, timeout=timeout,
            cleanup_timeout=cleanup_timeout, input_limit=4*1024*1024,
            stdout_limit=65536, stderr_limit=65536)

    def shadow(self, snapshot, proposal, binding):
        return self._call('shadow', dict(snapshot=_parse(snapshot, 4*1024*1024),
            proposal=_parse(proposal, 65536), binding=_parse(binding, 65536)))

    def prepared(self, request, snapshot):
        return self._call('prepared', dict(request=_parse(request, 4*1024*1024),
                                          snapshot=_parse(snapshot, 4*1024*1024)))

    def _call(self, stage, body):
        request_id = uuid.uuid4().hex
        payload = encoded(dict(version=1, stage=stage, request_id=request_id,
            check_id=self.check_id, provider_id=self.provider_id, body=body))
        raw = self.transport(payload)
        reply = _parse(raw, 65536)
        if (not isinstance(reply, dict) or set(reply) != {'version', 'request_id',
                'request_sha256', 'check_id', 'provider_id', 'status', 'evidence_ref'}
                or type(reply['version']) is not int or reply['version'] != 1
                or reply['request_id'] != request_id
                or reply['request_sha256'] != hashlib.sha256(payload).hexdigest()
                or reply['check_id'] != self.check_id or reply['provider_id'] != self.provider_id):
            raise ValueError('provider response does not match this request')
        binding = dict(task_id=request_id, target=stage, revision='wire', proposal_sha256='0'*64)
        decide(binding, {self.check_id: self.provider_id}, [dict(
            check_id=self.check_id, provider_id=self.provider_id, binding=binding,
            status=reply['status'], evidence_ref=reply['evidence_ref'])])
        return dict(status=reply['status'], evidence_ref=reply['evidence_ref'])
