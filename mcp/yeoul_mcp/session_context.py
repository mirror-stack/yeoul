"""Opt-in persistent session state and bounded replacement context.

Host-owned library, not an MCP write endpoint or a language understanding model.
Unstructured turns remain pending until a host reviews an extraction proposal.
SQLite records are authoritative only within the trusted host account boundary.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import uuid

from .context_shadow import encoded
from .workspace import checked_path

KINDS = {'goal', 'policy', 'constraint', 'decision', 'task', 'blocker'}
ORIGINS = {'user', 'tool', 'assistant', 'trace'}


def require(value, message):
    if not value:
        raise ValueError(message)


class SessionContext:
    """Explicit create/open; callers close this object or use a context manager.

    record/review are trusted-host operations. Text never grants their authority.
    revision CAS and BEGIN IMMEDIATE serialize writers across processes.
    """
    @classmethod
    def create(cls, path, *, max_events=100000, max_payload_bytes=67108864,
               max_database_bytes=268435456, min_free_bytes=67108864):
        path = checked_path(path)
        require(path.parent.is_dir(), 'parent must already exist')
        require(type(max_events) is int and 1 <= max_events <= 1000000,
                'invalid journal event limit')
        require(type(max_payload_bytes) is int and 1024 <= max_payload_bytes <= 1073741824,
                'invalid journal byte limit')
        require(type(max_database_bytes) is int and
                1048576 <= max_database_bytes <= 4294967296 and
                max_database_bytes >= max_payload_bytes,
                'invalid journal database limit')
        require(type(min_free_bytes) is int and 0 <= min_free_bytes <= 9223372036854775807,
                'invalid journal free-space floor')
        require(cls._free_bytes(path.parent) >= min_free_bytes,
                'journal filesystem free-space floor reached')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            db = sqlite3.connect(path)
            try:
                db.executescript('''
                    CREATE TABLE meta(version INTEGER NOT NULL, session TEXT NOT NULL);
                    CREATE TABLE log(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL,
                                     parent TEXT NOT NULL, digest TEXT NOT NULL);
                    CREATE TABLE limits(max_events INTEGER NOT NULL,
                        max_payload_bytes INTEGER NOT NULL, event_count INTEGER NOT NULL,
                        payload_bytes INTEGER NOT NULL, max_database_bytes INTEGER NOT NULL,
                        min_free_bytes INTEGER NOT NULL);
                    CREATE TRIGGER no_update BEFORE UPDATE ON log BEGIN
                        SELECT RAISE(ABORT, 'append only'); END;
                    CREATE TRIGGER no_delete BEFORE DELETE ON log BEGIN
                        SELECT RAISE(ABORT, 'append only'); END;
                ''')
                db.execute('INSERT INTO meta VALUES(1,?)', (uuid.uuid4().hex,))
                db.execute('INSERT INTO limits VALUES(?,?,0,0,?,?)',
                           (max_events, max_payload_bytes, max_database_bytes, min_free_bytes))
                db.commit()
                # Optional derived acceleration. Older/limited SQLite builds continue
                # with bounded journal scanning when FTS5 trigram is unavailable.
                try:
                    db.execute('SAVEPOINT search_index_setup')
                    db.execute("CREATE VIRTUAL TABLE turn_search USING fts5(text, tokenize='trigram case_sensitive 1')")
                    db.execute('''CREATE TABLE search_meta(revision INTEGER NOT NULL,
                        head TEXT NOT NULL, turn_count INTEGER NOT NULL,
                        search_digest TEXT NOT NULL)''')
                    db.execute('INSERT INTO search_meta VALUES(0,?,0,?)', ('0' * 64, '0' * 64))
                    db.execute('RELEASE search_index_setup')
                    db.commit()
                except sqlite3.OperationalError:
                    if db.in_transaction:
                        db.execute('ROLLBACK TO search_index_setup')
                        db.execute('RELEASE search_index_setup')
                        db.commit()
            finally:
                db.close()
            return cls(path)
        except Exception:
            # os.open(O_EXCL) proved this invocation created the path. Do not
            # strand an unusable placeholder/partial database that blocks a
            # corrected retry. Existing paths fail before this cleanup scope.
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    def __init__(self, path, *, use_checkpoint=False):
        require(type(use_checkpoint) is bool, 'invalid checkpoint mode')
        self.path = checked_path(path, existing=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            rows = self.db.execute('SELECT version,session FROM meta').fetchall()
            require(len(rows) == 1 and rows[0][0] == 1, 'unsupported session database')
            self.session = rows[0][1]
            self._revision = 0
            self._head = '0' * 64
            self._items = {}
            self._pending = {}
            self._search_enabled = False
            self._search_verified = False
            self._search_replay_complete = True
            self._search_digest = '0' * 64
            self._search_turn_count = 0
            self._search_checked_revision = None
            self._search_ignored = 'unavailable'
            self._load_search_schema()
            self._full_verified = False
            self._checkpoint_revision = None
            self._checkpoint_ignored = None
            self._load_checkpoint(use_checkpoint)
            self._refresh()
            if self._checkpoint_revision is None:
                self._full_verified = True
            self._load_limits()
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _reduce(items, pending, seq, event):
        if event['type'] == 'turn':
            if event['origin'] != 'trace':
                pending[seq] = {'turn': seq, 'origin': event['origin'], 'text': event['text']}
        elif event['type'] == 'review':
            require(event['turn'] in pending, 'turn already reviewed or unavailable')
            for change in event['changes']:
                item = dict(change, turn=event['turn'], revision=seq)
                items[(item['kind'], item['key'])] = item
            del pending[event['turn']]
        else:
            raise ValueError('unknown log event')

    @staticmethod
    def _next_search_digest(previous, seq, text):
        return hashlib.sha256(encoded([previous, seq, text])).hexdigest()

    @staticmethod
    def _free_bytes(path):
        # shutil.disk_usage is backed by statvfs on POSIX and the native volume
        # API on Windows.  Session creation must not depend on a POSIX-only API.
        return shutil.disk_usage(path).free

    def _check_free_space(self):
        if self._limits is not None and self._limits.get('min_free_bytes', 0):
            try:
                free = self._free_bytes(self.path.parent)
            except OSError:
                raise ValueError('journal filesystem free-space unavailable') from None
            require(free >= self._limits['min_free_bytes'],
                    'journal filesystem free-space floor reached')
            return free
        return None

    def _load_search_schema(self):
        tables = {row[0] for row in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('turn_search','search_meta')")}
        if not tables:
            return
        if tables != {'turn_search', 'search_meta'}:
            self._search_ignored = 'invalid_schema'
            return
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(turn_search)')]
        meta_columns = [row[1] for row in self.db.execute('PRAGMA table_info(search_meta)')]
        if columns != ['text'] or meta_columns != ['revision','head','turn_count','search_digest']:
            self._search_ignored = 'invalid_schema'
            return
        self._search_enabled = True
        self._search_ignored = None

    def _validate_search_index(self):
        if not self._search_enabled or self._search_checked_revision == self._revision:
            return
        self._search_verified = False
        if not self._search_replay_complete:
            self._search_ignored = 'checkpoint_prefix_unverified'
            self._search_checked_revision = self._revision
            return
        try:
            rows = self.db.execute(
                'SELECT revision,head,turn_count,search_digest FROM search_meta').fetchall()
            require(len(rows) == 1, 'invalid search index metadata')
            revision, head, count, digest = rows[0]
            actual_count = self.db.execute('SELECT count(*) FROM turn_search').fetchone()[0]
            require(revision == self._revision and head == self._head and
                    count == self._search_turn_count == actual_count and
                    digest == self._search_digest,
                    'search index does not match journal')
            if self._search_checked_revision is None:
                indexed_digest, indexed_count = '0' * 64, 0
                for seq, text in self.db.execute(
                        'SELECT rowid,text FROM turn_search ORDER BY rowid'):
                    require(type(seq) is int and isinstance(text, str),
                            'invalid search index row')
                    indexed_digest = self._next_search_digest(indexed_digest, seq, text)
                    indexed_count += 1
                require(indexed_count == count and indexed_digest == digest,
                        'search index content does not match journal')
            self._search_verified = True
            self._search_ignored = None
        except (ValueError, TypeError, sqlite3.DatabaseError):
            self._search_enabled = False
            self._search_ignored = 'invalid'
        self._search_checked_revision = self._revision

    def search_index_status(self):
        self._refresh()
        return dict(available=self._search_enabled, verified=self._search_verified,
                    revision=self._revision if self._search_verified else None,
                    turn_count=self._search_turn_count if self._search_replay_complete else None,
                    reason=self._search_ignored)

    def rebuild_search_index(self, *, expected_revision):
        """Explicitly replace only the derived index; source log stays untouched."""
        require(type(expected_revision) is int and expected_revision >= 0, 'invalid revision')
        require(self._full_verified, 'full replay verification required before index rebuild')
        require(self._limits is not None and 'max_database_bytes' in self._limits,
                'bounded main database required before index rebuild')
        self._check_free_space()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._refresh()
            require(self._revision == expected_revision, 'stale session revision')
            self.db.execute('DROP TABLE IF EXISTS turn_search')
            self.db.execute('DROP TABLE IF EXISTS search_meta')
            self.db.execute(
                "CREATE VIRTUAL TABLE turn_search USING fts5(text, tokenize='trigram case_sensitive 1')")
            self.db.execute('''CREATE TABLE search_meta(revision INTEGER NOT NULL,
                head TEXT NOT NULL, turn_count INTEGER NOT NULL,
                search_digest TEXT NOT NULL)''')
            digest, count = '0' * 64, 0
            for seq, payload in self.db.execute('SELECT seq,payload FROM log ORDER BY seq'):
                event = json.loads(payload)
                if event['type'] == 'turn':
                    self.db.execute('INSERT INTO turn_search(rowid,text) VALUES(?,?)',
                                    (seq, event['text']))
                    digest = self._next_search_digest(digest, seq, event['text'])
                    count += 1
            self.db.execute('INSERT INTO search_meta VALUES(?,?,?,?)',
                            (self._revision, self._head, count, digest))
            self.db.execute('COMMIT')
        except sqlite3.OperationalError as exc:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            if (getattr(exc, 'sqlite_errorcode', None) == getattr(sqlite3, 'SQLITE_FULL', 13) or
                    'database or disk is full' in str(exc).lower()):
                raise ValueError('journal database byte limit reached') from exc
            if 'fts5' in str(exc).lower() or 'tokenizer' in str(exc).lower():
                raise ValueError('case-sensitive trigram search index unavailable') from exc
            raise
        except Exception:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        self._search_enabled = False
        self._search_verified = False
        self._search_replay_complete = True
        self._search_digest = digest
        self._search_turn_count = count
        self._search_checked_revision = None
        self._search_ignored = 'unavailable'
        self._load_search_schema()
        self._validate_search_index()
        require(self._search_verified, 'rebuilt search index verification failed')
        usage = self.journal_usage()
        return dict(revision=self._revision, indexed_turns=count,
                    source_events_preserved=usage['event_count'],
                    database_bytes=usage.get('database_bytes'))

    def _refresh(self):
        rows = self.db.execute('SELECT seq,payload,parent,digest FROM log WHERE seq>? ORDER BY seq',
                               (self._revision,))
        for seq, payload, parent, digest in rows:
            require(seq == self._revision + 1 and parent == self._head, 'broken journal chain')
            event = json.loads(payload)
            expected = hashlib.sha256(encoded([self.session, seq, parent, event])).hexdigest()
            require(digest == expected, 'changed journal payload')
            self._reduce(self._items, self._pending, seq, event)
            if self._search_replay_complete and event['type'] == 'turn':
                self._search_digest = self._next_search_digest(
                    self._search_digest, seq, event['text'])
                self._search_turn_count += 1
            self._revision, self._head = seq, digest
        self._validate_search_index()

    @staticmethod
    def _checkpoint_snapshot(items, pending):
        return dict(version=1,
                    items=[items[key] for key in sorted(items)],
                    pending=[pending[key] for key in sorted(pending)])

    @staticmethod
    def _restore_checkpoint(snapshot, maximum_revision):
        require(isinstance(snapshot, dict) and set(snapshot) == {'version', 'items', 'pending'}
                and snapshot['version'] == 1 and isinstance(snapshot['items'], list)
                and isinstance(snapshot['pending'], list), 'invalid checkpoint payload')
        items, pending = {}, {}
        item_fields = {'kind','key','text','status','start','end','quote','evidence','reopen',
                       'turn','revision'}
        for item in snapshot['items']:
            allowed = ({'open','done','failed'} if isinstance(item, dict) and
                       item.get('kind') == 'task' else {'active','revoked'})
            require(isinstance(item, dict) and set(item) == item_fields and
                    item['kind'] in KINDS and isinstance(item['key'], str) and item['key'] and
                    len(item['key']) <= 128 and isinstance(item['text'], str) and item['text'] and
                    len(item['text'].encode()) <= 8192 and item['status'] in allowed and
                    type(item['start']) is int and type(item['end']) is int and
                    0 <= item['start'] < item['end'] and isinstance(item['quote'], str) and
                    item['quote'] and isinstance(item['evidence'], str) and
                    type(item['reopen']) is bool and
                    type(item['turn']) is int and 0 < item['turn'] <= maximum_revision and
                    type(item['revision']) is int and item['turn'] < item['revision'] <= maximum_revision,
                    'invalid checkpoint item')
            key = item['kind'], item['key']
            require(key not in items, 'duplicate checkpoint item')
            items[key] = item
        for item in snapshot['pending']:
            require(isinstance(item, dict) and set(item) == {'turn','origin','text'} and
                    type(item['turn']) is int and 0 < item['turn'] <= maximum_revision and
                    item['origin'] in ORIGINS and isinstance(item['text'], str) and
                    bool(item['text'].strip()),
                    'invalid checkpoint pending turn')
            require(item['turn'] not in pending, 'duplicate checkpoint pending turn')
            pending[item['turn']] = item
        return items, pending

    def _load_checkpoint(self, enabled):
        """Load only a derived projection. Invalid artifacts fall back to full replay."""
        if not enabled:
            return
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint'").fetchone()
        if not exists:
            self._checkpoint_ignored = 'missing'
            return
        try:
            columns = [row[1] for row in self.db.execute('PRAGMA table_info(checkpoint)')]
            require(columns == ['slot','seq','head','payload','digest'],
                    'invalid checkpoint table')
            rows = self.db.execute(
                'SELECT slot,seq,head,length(CAST(payload AS BLOB)),digest FROM checkpoint').fetchall()
            require(len(rows) == 1, 'checkpoint unavailable')
            slot, seq, head, size, digest = rows[0]
            require(slot == 1 and type(seq) is int and seq > 0 and
                    isinstance(head, str) and len(head) == 64 and
                    type(size) is int and 0 < size <= 8388608 and
                    isinstance(digest, str) and len(digest) == 64,
                    'invalid checkpoint metadata')
            payload = self.db.execute('SELECT payload FROM checkpoint WHERE slot=1').fetchone()[0]
            snapshot = json.loads(payload)
            require(encoded(snapshot).decode() == payload, 'noncanonical checkpoint payload')
            anchor = self.db.execute('SELECT digest FROM log WHERE seq=?', (seq,)).fetchone()
            require(anchor is not None and anchor[0] == head, 'checkpoint anchor unavailable')
            expected = hashlib.sha256(encoded([self.session, seq, head, snapshot])).hexdigest()
            require(digest == expected, 'changed checkpoint payload')
            self._items, self._pending = self._restore_checkpoint(snapshot, seq)
            self._revision, self._head = seq, head
            self._checkpoint_revision = seq
            self._search_replay_complete = False
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
            self._revision = 0
            self._head = '0' * 64
            self._items = {}
            self._pending = {}
            self._checkpoint_revision = None
            self._checkpoint_ignored = 'invalid'

    def replay_status(self):
        """Describe replay provenance; this is not a journal-integrity verdict."""
        self._refresh()
        return dict(mode='checkpoint' if self._checkpoint_revision is not None else 'full',
                    checkpoint_revision=self._checkpoint_revision,
                    current_revision=self._revision,
                    replayed_events=(self._revision - (self._checkpoint_revision or 0)),
                    full_prefix_verified=self._full_verified,
                    checkpoint_ignored=self._checkpoint_ignored)

    def verify_full(self):
        """Recompute the complete chain/projection and compare it with current state."""
        self.db.execute('BEGIN')
        try:
            self._refresh()
            items, pending, revision, head = {}, {}, 0, '0' * 64
            search_digest, turn_count = '0' * 64, 0
            rows = self.db.execute('SELECT seq,payload,parent,digest FROM log ORDER BY seq')
            for seq, payload, parent, digest in rows:
                require(seq == revision + 1 and parent == head, 'broken journal chain')
                event = json.loads(payload)
                expected = hashlib.sha256(encoded([self.session, seq, parent, event])).hexdigest()
                require(digest == expected, 'changed journal payload')
                self._reduce(items, pending, seq, event)
                if event['type'] == 'turn':
                    search_digest = self._next_search_digest(search_digest, seq, event['text'])
                    turn_count += 1
                revision, head = seq, digest
            require(revision == self._revision and head == self._head and
                    items == self._items and pending == self._pending,
                    'checkpoint projection mismatch')
            if self._search_enabled:
                meta = self.db.execute(
                    'SELECT revision,head,turn_count,search_digest FROM search_meta').fetchall()
                require(len(meta) == 1 and meta[0] == (revision, head, turn_count, search_digest)
                        and self.db.execute('SELECT count(*) FROM turn_search').fetchone()[0] == turn_count,
                        'search index does not match journal')
        finally:
            self.db.execute('ROLLBACK')
        self._full_verified = True
        self._search_replay_complete = True
        self._search_digest = search_digest
        self._search_turn_count = turn_count
        self._search_checked_revision = None
        self._validate_search_index()
        return self.replay_status()

    def write_checkpoint(self, *, expected_revision):
        """Replace a derived acceleration artifact; never remove source log events."""
        require(type(expected_revision) is int and expected_revision >= 0, 'invalid revision')
        require(self._full_verified, 'full replay verification required before checkpoint')
        self._check_free_space()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._refresh()
            require(self._revision == expected_revision, 'stale session revision')
            require(self._revision > 0, 'empty journal checkpoint refused')
            snapshot = self._checkpoint_snapshot(self._items, self._pending)
            payload = encoded(snapshot)
            require(len(payload) <= 8388608, 'checkpoint exceeds 8 MiB')
            digest = hashlib.sha256(
                encoded([self.session, self._revision, self._head, snapshot])).hexdigest()
            self.db.execute('''CREATE TABLE IF NOT EXISTS checkpoint(
                slot INTEGER PRIMARY KEY CHECK(slot=1), seq INTEGER NOT NULL,
                head TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL)''')
            self.db.execute('DELETE FROM checkpoint')
            self.db.execute('INSERT INTO checkpoint VALUES(1,?,?,?,?)',
                            (self._revision, self._head, payload.decode(), digest))
            self.db.execute('COMMIT')
        except sqlite3.OperationalError as exc:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            if (getattr(exc, 'sqlite_errorcode', None) == getattr(sqlite3, 'SQLITE_FULL', 13) or
                    'database or disk is full' in str(exc).lower()):
                raise ValueError('journal database byte limit reached') from exc
            raise
        except Exception:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        return dict(revision=self._revision, head=self._head, checkpoint_bytes=len(payload),
                    source_events_preserved=self._revision)

    def _load_limits(self):
        """Load additive schema limits; old version-1 databases stay readable."""
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='limits'").fetchone()
        if not exists:
            self._limits = None
            return
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(limits)')]
        old = ['max_events', 'max_payload_bytes', 'event_count', 'payload_bytes']
        database = old + ['max_database_bytes']
        new = database + ['min_free_bytes']
        require(columns in (old, database, new), 'invalid journal limits')
        rows = self.db.execute('SELECT ' + ','.join(columns) + ' FROM limits').fetchall()
        require(len(rows) == 1, 'invalid journal limits')
        maximum_events, maximum_bytes, event_count, payload_bytes = rows[0][:4]
        require(type(maximum_events) is int and 1 <= maximum_events <= 1000000 and
                type(maximum_bytes) is int and 1024 <= maximum_bytes <= 1073741824 and
                type(event_count) is int and type(payload_bytes) is int and
                event_count >= 0 and payload_bytes >= 0, 'invalid journal limits')
        actual = self.db.execute(
            'SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM log').fetchone()
        require(actual == (event_count, payload_bytes), 'journal usage counter mismatch')
        self._limits = dict(max_events=maximum_events, max_payload_bytes=maximum_bytes,
                            event_count=event_count, payload_bytes=payload_bytes)
        if columns in (database, new):
            maximum_database_bytes = rows[0][4]
            require(type(maximum_database_bytes) is int and
                    1048576 <= maximum_database_bytes <= 4294967296 and
                    maximum_database_bytes >= maximum_bytes,
                    'invalid journal database limit')
            require(self.db.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'delete',
                    'bounded journal requires delete journal mode')
            page_size = self.db.execute('PRAGMA page_size').fetchone()[0]
            page_count = self.db.execute('PRAGMA page_count').fetchone()[0]
            maximum_pages = maximum_database_bytes // page_size
            require(maximum_pages >= page_count, 'journal database limit already exceeded')
            applied = self.db.execute('PRAGMA max_page_count=%d' % maximum_pages).fetchone()[0]
            require(applied == maximum_pages, 'journal database limit unavailable')
            self._limits['max_database_bytes'] = maximum_database_bytes
        if columns == new:
            minimum_free_bytes = rows[0][5]
            require(type(minimum_free_bytes) is int and
                    0 <= minimum_free_bytes <= 9223372036854775807,
                    'invalid journal free-space floor')
            self._limits['min_free_bytes'] = minimum_free_bytes

    def journal_usage(self):
        """Report canonical payload and, on new schemas, allocated main-DB pages."""
        self._refresh()
        if self._limits is None:
            count, size = self.db.execute(
                'SELECT count(*),coalesce(sum(length(CAST(payload AS BLOB))),0) FROM log').fetchone()
            return dict(bounded=False, event_count=count, payload_bytes=size,
                        max_events=None, max_payload_bytes=None)
        row = self.db.execute(
            'SELECT max_events,max_payload_bytes,event_count,payload_bytes FROM limits').fetchone()
        require(row is not None, 'journal limits missing')
        maximum_events, maximum_bytes, count, size = row
        result = dict(bounded=True, event_count=count, payload_bytes=size,
                      max_events=maximum_events, max_payload_bytes=maximum_bytes)
        if 'max_database_bytes' in self._limits:
            page_size = self.db.execute('PRAGMA page_size').fetchone()[0]
            page_count = self.db.execute('PRAGMA page_count').fetchone()[0]
            result.update(database_bytes=page_size * page_count,
                          max_database_bytes=self._limits['max_database_bytes'])
        if 'min_free_bytes' in self._limits:
            result.update(min_free_bytes=self._limits['min_free_bytes'],
                          free_space_reserved=False)
        return result

    def storage_status(self):
        """Read-only observation; free bytes are not reserved for this journal."""
        usage = self.journal_usage()
        try:
            free = self._free_bytes(self.path.parent)
        except OSError:
            free = None
        return dict(**usage, observed_free_bytes=free, hard_filesystem_quota=False,
                    rollback_journal_bounded=False, observation_only=True)

    @property
    def revision(self):
        self._refresh()
        return self._revision

    def _append(self, expected_revision, make_event):
        require(type(expected_revision) is int and expected_revision >= 0, 'invalid revision')
        self._check_free_space()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._refresh()
            require(self._revision == expected_revision, 'stale session revision')
            event = make_event()
            payload = encoded(event)
            require(len(payload) <= 262144, 'event exceeds 256 KiB')
            if self._limits is not None:
                maximum_events, maximum_bytes, count, size = self.db.execute(
                    'SELECT max_events,max_payload_bytes,event_count,payload_bytes FROM limits').fetchone()
                require(count < maximum_events, 'journal event limit reached')
                require(size + len(payload) <= maximum_bytes, 'journal byte limit reached')
            seq = self._revision + 1
            digest = hashlib.sha256(encoded([self.session, seq, self._head, event])).hexdigest()
            self.db.execute('INSERT INTO log VALUES(?,?,?,?)', (seq, payload.decode(), self._head, digest))
            if self._search_enabled:
                rows = self.db.execute(
                    'SELECT revision,head,turn_count,search_digest FROM search_meta').fetchall()
                require(len(rows) == 1 and rows[0][0] == self._revision and
                        rows[0][1] == self._head, 'search index metadata is stale')
                _, _, turn_count, search_digest = rows[0]
                if event['type'] == 'turn':
                    self.db.execute('INSERT INTO turn_search(rowid,text) VALUES(?,?)',
                                    (seq, event['text']))
                    turn_count += 1
                    search_digest = self._next_search_digest(search_digest, seq, event['text'])
                self.db.execute('''UPDATE search_meta SET revision=?,head=?,turn_count=?,
                    search_digest=?''', (seq, digest, turn_count, search_digest))
            if self._limits is not None:
                self.db.execute('UPDATE limits SET event_count=event_count+1,payload_bytes=payload_bytes+?',
                                (len(payload),))
            self.db.execute('COMMIT')
        except sqlite3.OperationalError as exc:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            if (getattr(exc, 'sqlite_errorcode', None) == getattr(sqlite3, 'SQLITE_FULL', 13) or
                    'database or disk is full' in str(exc).lower()):
                raise ValueError('journal database byte limit reached') from exc
            raise
        except Exception:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        self._refresh()
        if self._limits is not None:
            self._limits['event_count'] += 1
            self._limits['payload_bytes'] += len(payload)
        return seq

    def record(self, text, *, origin, expected_revision):
        require(isinstance(text, str) and bool(text.strip()), 'empty turn')
        require(origin in ORIGINS, 'invalid origin')
        return self._append(expected_revision, lambda: dict(type='turn', text=text, origin=origin))

    def review(self, turn, changes, *, expected_revision, reason, dry_run=False):
        """Accept host-reviewed structured changes, or explicitly dismiss a turn.

        Exact quotes bind proposals to source spans, NOT semantic correctness.
        A completed task requires a tool-origin turn and a host evidence reference.
        A reopened task requires an explicit reopen flag and a user-origin turn.
        """
        require(type(turn) is int and isinstance(reason, str) and reason.strip(), 'review reason required')
        require(isinstance(changes, list) and len(changes) <= 100, 'invalid changes')
        frozen = json.loads(encoded(changes))

        def event():
            require(turn in self._pending, 'pending turn required')
            source = self._pending[turn]
            require(not frozen or source['origin'] in ('user', 'tool'), 'assistant proposals cannot change state')
            seen = set()
            for c in frozen:
                require(isinstance(c, dict) and set(c) == {
                    'kind','key','text','status','start','end','quote','evidence','reopen'}, 'invalid change schema')
                require(c['kind'] in KINDS, 'unknown state kind')
                require(all(isinstance(c[k], str) and c[k].strip() for k in ('key','text','quote')), 'empty state field')
                require(len(c['key']) <= 128 and len(c['text'].encode()) <= 8192, 'state field too large')
                require(isinstance(c['evidence'], str) and type(c['reopen']) is bool, 'invalid evidence/reopen')
                key = c['kind'], c['key']
                require(key not in seen, 'duplicate change key')
                seen.add(key)
                require(type(c['start']) is int and type(c['end']) is int and
                    0 <= c['start'] < c['end'] <= len(source['text']) and
                    source['text'][c['start']:c['end']] == c['quote'], 'source quote mismatch')
                allowed = {'active','revoked'} if c['kind'] != 'task' else {'open','done','failed'}
                require(c['status'] in allowed, 'invalid status')
                require(c['kind'] in ('task','blocker') or source['origin'] == 'user', 'user-origin policy change required')
                if c['status'] == 'done':
                    require(source['origin'] == 'tool' and c['evidence'].strip(), 'verified completion evidence required')
                old = self._items.get(key)
                if old and old['status'] == 'done' and c['status'] != 'done':
                    require(c['reopen'] and source['origin'] == 'user', 'explicit user reopen required')
                if c['reopen']:
                    require(old and old['status'] == 'done' and c['status'] == 'open' and
                            source['origin'] == 'user', 'invalid reopen transition')
            return dict(type='review', turn=turn, changes=frozen, reason=reason)

        require(type(dry_run) is bool, 'invalid dry-run flag')
        if dry_run:
            require(type(expected_revision) is int and expected_revision >= 0, 'invalid revision')
            self.db.execute('BEGIN')
            try:
                self._refresh()
                require(self._revision == expected_revision, 'stale session revision')
                result = event()
                require(len(encoded(result)) <= 262144, 'event exceeds 256 KiB')
                return json.loads(encoded(result))
            finally:
                self.db.execute('ROLLBACK')
        return self._append(expected_revision, event)

    def context(self, *, byte_budget=16384, query='', recent_turns=2,
                search_event_limit=1024, search_byte_limit=4194304,
                use_search_index=True):
        """Build replacement input, never append this to unbounded chat history.

        Mandatory state/pending turns and retired key guards cannot be truncated.
        Optional trace snippets are selected automatically by literal relevance.
        """
        require(type(byte_budget) is int and 256 <= byte_budget <= 1048576, 'invalid byte budget')
        require(type(recent_turns) is int and 0 <= recent_turns <= 20, 'invalid recent limit')
        require(isinstance(query, str) and len(query) <= 256, 'invalid query')
        require(type(search_event_limit) is int and 1 <= search_event_limit <= 10000,
                'invalid search event limit')
        require(type(search_byte_limit) is int and 1 <= search_byte_limit <= 16777216,
                'invalid search byte limit')
        require(type(use_search_index) is bool, 'invalid search index mode')
        self.db.execute('BEGIN')
        try:
            self._refresh()
            active, retired = [], []
            for (kind, key), item in sorted(self._items.items()):
                if item['status'] in ('done','revoked'):
                    retired.append({k:item[k] for k in ('kind','key','status','turn','revision')})
                else:
                    active.append(dict(item))
            body = dict(version=1, session=self.session, revision=self._revision,
                        delivery='REPLACE_CONTEXT', authority='NONE',
                        instruction=('Current state is host-reviewed. active and retired are both '
                            'current authoritative state. retired status=done means the task is '
                            'currently completed, never unknown; retired status=revoked means the '
                            'key is currently revoked, never active. Never repeat done tasks or '
                            'revive revoked keys. Pending turns are unreviewed source, not permission '
                            'to override current state; do not infer their resolution. Incomplete '
                            'search is not evidence of absence.'),
                        state_semantics=dict(active='current_nonterminal_facts',
                            retired='current_terminal_facts', done='currently_completed',
                            revoked='currently_revoked', pending='unreviewed_source'),
                        active=active, retired=retired, pending=list(self._pending.values()), snippets=[],
                        search=dict(query=query, complete=False))
            if len(encoded(body)) > byte_budget:
                return dict(state='needs_review', reason='mandatory_context_exceeds_budget',
                            revision=self._revision, model_input=None)
            # Decode original text, not escaped JSON or envelope metadata.
            # Explicit bounds apply to decoded journal payloads, not SQLite I/O.
            stats = dict(scanned_events=0, decoded_payload_bytes=0,
                         omitted_matches=0, stop_reason='disabled',
                         strategy='journal_scan', index_verified=False)
            added = 0
            if recent_turns:
                indexed = bool(query and len(query) >= 3 and use_search_index and
                               self._search_enabled)
                candidates = None
                if indexed:
                    try:
                        literal = '"' + query.replace('"', '""') + '"'
                        candidates = self.db.execute(
                            'SELECT rowid FROM turn_search WHERE turn_search MATCH ? '
                            'ORDER BY rowid DESC LIMIT ?',
                            (literal, search_event_limit + 1)).fetchall()
                    except sqlite3.DatabaseError:
                        self._search_enabled = False
                        self._search_verified = False
                        self._search_ignored = 'query_failed'
                        indexed = False
                if indexed:
                    stats.update(strategy='fts5_trigram', index_verified=self._search_verified,
                                 stop_reason='index_end')
                    more = len(candidates) > search_event_limit
                    selected = candidates[:search_event_limit]
                    for position, (seq,) in enumerate(selected):
                        row = self.db.execute('SELECT payload FROM log WHERE seq=?', (seq,)).fetchone()
                        if row is None:
                            indexed = False
                            break
                        payload = row[0]
                        size = len(payload.encode('utf-8'))
                        if stats['decoded_payload_bytes'] + size > search_byte_limit:
                            stats['stop_reason'] = 'byte_limit'
                            break
                        stats['decoded_payload_bytes'] += size
                        stats['scanned_events'] += 1
                        event = json.loads(payload)
                        if event.get('type') != 'turn' or event['text'].find(query) < 0:
                            indexed = False
                            break
                        if seq not in self._pending:
                            text = event['text']
                            match = text.find(query)
                            start = max(0, min(match - 200, len(text) - 1000))
                            end = min(len(text), start + 1000)
                            snippet = dict(turn=seq, historical=True, start=start, end=end,
                                text=text[start:end], truncated=start > 0 or end < len(text))
                            body['snippets'].append(snippet)
                            if len(encoded(body)) > byte_budget:
                                body['snippets'].pop()
                                stats['omitted_matches'] += 1
                            else:
                                added += 1
                        if added >= recent_turns:
                            if position + 1 < len(selected) or more:
                                stats['stop_reason'] = 'snippet_limit'
                            break
                    if indexed and stats['stop_reason'] == 'index_end':
                        if more:
                            stats['stop_reason'] = 'event_limit'
                        elif not self._search_verified:
                            stats['stop_reason'] = 'index_unverified'
                if not indexed:
                    body['snippets'] = []
                    stats = dict(scanned_events=0, decoded_payload_bytes=0,
                                 omitted_matches=0, stop_reason='event_limit',
                                 strategy='journal_scan', index_verified=False)
                    added = 0
                    cursor = self.db.execute('SELECT seq,payload FROM log ORDER BY seq DESC')
                    for _ in range(search_event_limit):
                        row = cursor.fetchone()
                        if row is None:
                            stats['stop_reason'] = 'archive_end'
                            break
                        seq, payload = row
                        size = len(payload.encode('utf-8'))
                        if stats['decoded_payload_bytes'] + size > search_byte_limit:
                            stats['stop_reason'] = 'byte_limit'
                            break
                        stats['decoded_payload_bytes'] += size
                        stats['scanned_events'] += 1
                        event = json.loads(payload)
                        if event['type'] == 'turn' and seq not in self._pending:
                            text = event['text']
                            match = text.find(query)  # Exact, case-sensitive Unicode match.
                            if match >= 0:
                                start = max(0, min(match - 200, len(text) - 1000))
                                end = min(len(text), start + 1000)
                                snippet = dict(turn=seq, historical=True, start=start, end=end,
                                    text=text[start:end], truncated=start > 0 or end < len(text))
                                body['snippets'].append(snippet)
                                if len(encoded(body)) > byte_budget:
                                    body['snippets'].pop()
                                    stats['omitted_matches'] += 1
                                else:
                                    added += 1
                        if seq == 1:
                            stats['stop_reason'] = 'archive_end'
                            break
                        if added >= recent_turns:
                            stats['stop_reason'] = 'snippet_limit'
                            break
                body['search']['complete'] = (stats['stop_reason'] in ('archive_end','index_end') and
                                               stats['omitted_matches'] == 0)
            raw = encoded(body)
            return dict(state='ready', revision=self._revision, model_input=raw,
                        sha256=hashlib.sha256(raw).hexdigest(), utf8_bytes=len(raw),
                        search_stats=stats)
        finally:
            self.db.execute('COMMIT')

    def retrieve(self, turn, *, start=0, limit=1000, expected_revision):
        """Explicit bounded source-range lookup; caller accounts for response bytes."""
        require(type(turn) is int and type(start) is int and start >= 0 and
                type(limit) is int and 1 <= limit <= 4000, 'invalid source range')
        require(type(expected_revision) is int and expected_revision >= 0, 'invalid revision')
        self.db.execute('BEGIN')
        try:
            self._refresh()
            require(expected_revision == self._revision, 'stale session revision')
            row = self.db.execute('SELECT payload FROM log WHERE seq=?', (turn,)).fetchone()
            require(row is not None, 'source missing')
            event = json.loads(row[0])
            require(event['type'] == 'turn' and start <= len(event['text']), 'invalid source turn')
            text = event['text']
            return encoded(dict(session=self.session, revision=self._revision, turn=turn,
                                start=start, end=min(len(text),start+limit), text=text[start:start+limit],
                                source_sha256=hashlib.sha256(text.encode()).hexdigest(), historical=True))
        finally:
            self.db.execute('COMMIT')
