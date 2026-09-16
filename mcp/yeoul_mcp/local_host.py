"""Opt-in host composition, not an MCP tool or a production service.

All callbacks are trusted host code. They must supply their own authenticated,
bounded transport. No model, provider, policy discovery or approval is defaulted.
"""
import json

from . import runtime
from .context_shadow import digest, encoded
from .file_sources import FileSources
from .product import workspace
from .review_decision import decide
from .reviewed_execution import execute_reviewed
from .shadow_workflow import run_shadow


class LocalHost:
    def __init__(self, root, *, worker, providers, allowed_tools):
        """providers: check -> (host provider ID, shadow callback, prepared callback).

        Shadow callbacks use run_shadow's contract. Prepared callbacks receive
        immutable (request_bytes, current_snapshot_bytes), where request contains
        the actual job and binding. They return only {status, evidence_ref}.
        The host, never a model proposal, chooses tool names and arguments.
        """
        self.sources = FileSources(root)
        self.root = root
        if not callable(worker) or not isinstance(providers, dict) or not providers:
            raise ValueError('explicit host worker and providers required')
        self.worker = worker
        self.providers = dict(providers)
        for spec in self.providers.values():
            if (not isinstance(spec, tuple) or len(spec) != 3
                    or not callable(spec[1]) or not callable(spec[2])):
                raise ValueError('separate shadow and prepared callbacks required')
        self.requirements = {check: spec[0] for check, spec in self.providers.items()}
        decide(dict(task_id='shape', target='shape', revision='shape', proposal_sha256='0'*64),
               self.requirements, [])
        if not isinstance(allowed_tools, (set, frozenset)) or not allowed_tools:
            raise ValueError('explicit tool allowlist required')
        self.allowed_tools = frozenset(allowed_tools)
        if not self.allowed_tools <= runtime.WRITE_TOOLS:
            raise ValueError('unknown allowed tool')

    def prepare(self, task_label, tool, arguments):
        workspace.require_managed(self.root)
        if tool not in self.allowed_tools or not isinstance(arguments, dict):
            raise ValueError('host operation not allowed')
        arguments = json.loads(encoded(arguments))
        result = run_shadow(task_label, self.sources.load_snapshot, self.worker,
                            {key: (spec[0], spec[1]) for key, spec in self.providers.items()})
        if result['state'] != 'ready_for_review':
            return result
        revision = result['binding']['revision']
        if digest(self.sources.load_snapshot()) != revision:
            raise ValueError('sources changed before preparation')
        proposal = dict(local_host_version=1, source_sha256=revision, candidate=result['proposal'])
        prepared = workspace.prepare(self.root, tool, arguments,
            review=dict(proposal=proposal, requirements=self.requirements))
        return dict(state='prepared', task_id=prepared['task_id'], authority='NONE',
                    execution='NOT_PERFORMED', shadow=result)

    def commit(self, task_id, *, approve):
        """Explicit host call only; approval callback receives the exact request bytes.

        Fresh sources and prepared verification are checked inside the existing
        write lock. Completed receipts keep the existing no-reexecution behavior.
        Local repeated reads are not a transaction with remote withdrawal systems.
        """
        workspace.require_managed(self.root)
        if not callable(approve):
            raise ValueError('explicit approval callback required')

        def review(request):
            current = json.loads(request)
            job = current['job']
            proposal = job['review']['proposal']
            if (job['tool'] not in self.allowed_tools
                    or job['review']['requirements'] != self.requirements
                    or set(proposal) != {'local_host_version', 'source_sha256', 'candidate'}
                    or type(proposal['local_host_version']) is not int
                    or proposal['local_host_version'] != 1
                    or not isinstance(proposal['candidate'], dict)):
                raise ValueError('operation does not match current host contract')

            def fresh():
                snapshot = self.sources.load_snapshot()
                if digest(snapshot) != proposal['source_sha256']:
                    raise ValueError('current source set differs from prepared source set')
                return encoded(snapshot)

            snapshot = fresh()
            reports = []
            for check, (provider_id, _, verify) in self.providers.items():
                report = verify(request, snapshot)
                if not isinstance(report, dict) or set(report) != {'status', 'evidence_ref'}:
                    raise ValueError('invalid prepared provider result')
                reports.append(dict(check_id=check, provider_id=provider_id,
                                    binding=current['binding'], **report))
            fresh()
            decision = decide(current['binding'], self.requirements, reports)
            approved = False
            if decision['state'] == 'ready_for_review':
                approved = approve(request)
                if type(approved) is not bool:
                    raise ValueError('approval must be an explicit boolean')
            fresh()
            return dict(approved=approved, reports=reports)

        return execute_reviewed(workspace, self.root, task_id, review)
