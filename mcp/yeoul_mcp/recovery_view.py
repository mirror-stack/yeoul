"""Read-only, serverless recovery view for a host's explicitly selected tasks.

No discovery, execution, service polling, record editing or administrative endpoint.
The host owns authentication, task selection and delivery of this sensitive snapshot.
"""
from datetime import datetime, timezone
from html import escape

from .worker_transport import WorkerTransportError


COPY = {
    'en': {
        'title': 'Yeoul recovery review', 'task': 'Task', 'status': 'Status', 'next': 'Next step',
        'notice': 'Read-only snapshot. This page does not stop, retry, delete or approve work. It may become outdated.',
        'empty': 'No authorized tasks to display.',
        'records': ('Records need review', 'Ask the host operator to inspect retained evidence. Do not delete or retry.'),
        'marker': ('Launch revocation is not recorded', 'Ask the host operator to resume cancellation recording and inspect the service.'),
        'unconfirmed': ('Stop is not confirmed', 'Ask an authorized operator to inspect the service and record a new observation.'),
        'observed': ('Service absence was observed', 'Queued-start and recovery checks remain. This is not cancellation completion.'),
        'cancel': ('Cancellation requested', 'An authorized operator must inspect or stop the service. Do not restart this task.'),
        'retired': ('Operator retirement recorded', 'Retirement is not proof of service cleanup or business completion.'),
        'output': ('Worker output retained', 'The output still needs the host workflow review; it is not business approval.'),
        'held': ('Execution needs review', 'Inspect retained execution evidence before any new work. Automatic retry is not allowed.'),
    },
    'ko': {
        'title': '여울 복구 점검', 'task': '작업', 'status': '상태', 'next': '다음 확인',
        'notice': '읽기 전용 스냅샷입니다. 중지·재실행·삭제·승인을 수행하지 않으며 현재 상태와 달라질 수 있습니다.',
        'empty': '표시할 권한이 있는 작업이 없습니다.',
        'records': ('기록 확인 필요', '호스트 관리자에게 보존된 기록 점검을 요청하세요. 삭제하거나 재실행하지 마세요.'),
        'marker': ('실행 철회 표시 미저장', '관리자에게 취소 기록 저장을 이어가고 서비스 상태를 확인하도록 요청하세요.'),
        'unconfirmed': ('중지 확인 필요', '권한이 있는 관리자가 서비스를 확인하고 새 관찰 결과를 기록해야 합니다.'),
        'observed': ('서비스 부재 관찰됨', '지연 요청과 복구 점검이 남아 있습니다. 취소 완료를 뜻하지 않습니다.'),
        'cancel': ('취소 요청됨', '권한이 있는 관리자가 서비스를 확인하거나 중지해야 합니다. 같은 작업을 재시작하지 마세요.'),
        'retired': ('관리자 종료 기록 있음', '이 기록만으로 서비스 정리나 업무 완료가 증명되지는 않습니다.'),
        'output': ('작업자 결과 보존됨', '호스트의 검토 절차가 남아 있습니다. 업무 승인이나 완료를 뜻하지 않습니다.'),
        'held': ('실행 점검 필요', '새 작업 전에 보존된 실행 기록을 확인하세요. 자동 재시도는 허용되지 않습니다.'),
    },
}


def _category(report):
    cancellation = report.get('cancellation')
    if cancellation:
        if cancellation['status'] == 'evidence_unreadable':
            return 'records'
        if cancellation.get('revocation_marker') == 'missing':
            return 'marker'
        if cancellation.get('unresolved_attempts', 0):
            return 'unconfirmed'
        attempts = cancellation.get('attempts', [])
        if attempts and all(a['state'] == 'absence_observed' for a in attempts):
            return 'observed'
        return 'cancel'
    if report['state'] == 'retired':
        return 'retired'
    if report['state'] == 'returned' and not report['needs_attention']:
        return 'output'
    return 'held'


def recovery_view(tasks, task_ids, *, language='en'):
    """Return bounded HTML while the host's authenticated request context is active.

    tasks is the trusted WorkerTasks instance, not request-supplied code. The host
    provides up to 100 logical IDs; unauthorized entries are omitted, not counted.
    A saved HTML file cannot be revoked: the host must protect its delivery/storage.
    """
    if language not in COPY or not isinstance(task_ids, (list, tuple)) or len(task_ids) > 100:
        raise ValueError('supported language and at most 100 explicit task IDs required')
    for task_id in task_ids:
        tasks._path(task_id)
    rows = []
    for task_id in dict.fromkeys(task_ids):
        try:
            tasks._permit(task_id, 'inspect')
            try:
                category = _category(tasks.inspect(task_id))
            except (OSError, ValueError):
                category = 'records'  # Never include exception text, paths or raw evidence.
            except WorkerTransportError as exc:
                if exc.reason == 'worker_task_permission_denied':
                    raise
                category = 'records'
            tasks._permit(task_id, 'inspect')
        except WorkerTransportError as exc:
            if exc.reason == 'worker_task_permission_denied':
                continue
            raise
        rows.append((task_id, category))
    copy = COPY[language]
    rendered = []
    for task_id, category in rows:
        # Recheck earlier rows after collection, including permission changes caused
        # by later host callbacks. This is a snapshot, not revocable browser access.
        try:
            tasks._permit(task_id, 'inspect')
        except WorkerTransportError as exc:
            if exc.reason == 'worker_task_permission_denied':
                continue
            raise
        status, action = copy[category]
        rendered.append('<tr><th scope="row">' + escape(task_id) + '</th><td data-label="' +
                        escape(copy['status'], quote=True) + '">' + escape(status) +
                        '</td><td data-label="' + escape(copy['next'], quote=True) + '">' +
                        escape(action) + '</td></tr>')
    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    body = ('<table><caption>' + escape(copy['title']) + '</caption><thead><tr>' +
            ''.join('<th scope="col">' + escape(copy[k]) + '</th>' for k in ('task', 'status', 'next')) +
            '</tr></thead><tbody>' + ''.join(rendered) + '</tbody></table>') if rendered else '<p>' + escape(copy['empty']) + '</p>'
    return ('<!doctype html><html lang="' + language + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<meta name="referrer" content="no-referrer"><title>' + escape(copy['title']) + '</title>'
            '<style>body{font:16px/1.6 system-ui,sans-serif;max-width:72rem;margin:auto;padding:1.5rem;color:#182432;background:#fafbfc}'
            'table{width:100%;table-layout:fixed;border-collapse:collapse;background:white}th,td{text-align:left;vertical-align:top;padding:1rem;border:1px solid #cad2dc;overflow-wrap:anywhere}'
            'thead th:nth-child(1),thead th:nth-child(2){width:22%}'
            'caption{text-align:left;font-weight:600;padding:.7rem 0}time{font-size:.85rem;overflow-wrap:anywhere}'
            '@media(max-width:600px){body{padding:1rem}table,caption,tbody,tr,th,td{display:block;width:auto}'
            'thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}'
            'tr{margin-bottom:1rem;border:1px solid #cad2dc}th,td{border:0;padding:.75rem}'
            'th[scope=row]{background:#edf1f6}td:before{content:attr(data-label);display:block;font-weight:600;margin-bottom:.25rem}}'
            '</style></head><body><main><h1>' +
            escape(copy['title']) + '</h1><p>' + escape(copy['notice']) + '</p><time datetime="' + timestamp + '">' +
            timestamp + '</time>' + body + '</main></body></html>')
