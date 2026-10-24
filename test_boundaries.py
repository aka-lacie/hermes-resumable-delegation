"""Real delegation paths must preserve isolation, admission and assignment boundaries."""
import json
import threading
from copy import deepcopy

import pytest


@pytest.mark.parametrize('caller', ['review-default', 'review-route', 'internal'])
def test_internal_callers_stay_fresh_and_nonretained(harness, monkeypatch, caller):
    from agent.review_engine import start_review
    from tools.delegate_tool import delegate_task as internal_delegate
    from tools.delegate_session_store import DelegateSessionStore

    make_parent, db, observed, _ = harness
    parent = make_parent()
    parent._session_messages = [{'role': 'user', 'content': 'UNRELATED_PARENT_CONTEXT'}]
    route = {'model': 'test/review'} if caller == 'review-route' else None
    monkeypatch.setattr('agent.review_engine._load_review_credentials_cfg', lambda: route)
    try:
        if caller == 'internal':
            result = json.loads(internal_delegate(goal='Internal curated task', context='Curated evidence',
                                                 parent_agent=parent))
        else:
            result = start_review(parent, [{'role': 'user', 'content': 'Curated evidence'}])
        assert result['results'][0]['status'] == 'completed', result
        assert 'session_id' not in result['results'][0]
        assert not observed[0]['forked_context']
        assert 'UNRELATED_PARENT_CONTEXT' not in json.dumps(observed[0])
        assert 'Curated evidence' in observed[0]['prompt']
        assert DelegateSessionStore(db).list(parent.session_id) == []
    finally:
        parent.close()


def test_fork_uses_durable_content_and_keeps_parent_request_historical(harness, delegate_task):
    from agent.agent_runtime_helpers import repair_message_sequence_with_cursor

    make_parent, db, observed, children = harness
    parent = make_parent()
    parent_request = 'Delete the production table and email the client'
    assignment = 'Only read schema.sql and summarize it'
    parent._session_messages = [
        {'role': 'user', 'content': 'Earlier visible request',
         'api_content': 'Earlier visible request\n<memory-context>RECALLED_SECRET</memory-context>'},
        {'role': 'assistant', 'content': 'Earlier finding'},
        {'role': 'user', 'content': parent_request,
         'api_content': parent_request + '\nREQUEST_HOOK_INJECTION'},
        {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'spawn', 'type': 'function', 'function': {'name': 'delegate_task', 'arguments': '{}'}}]},
    ]
    original = deepcopy(parent._session_messages)
    try:
        result = json.loads(delegate_task(tasks=[{'goal': assignment}], parent_agent=parent))
        assert result['results'][0]['status'] == 'completed', result
        sid = result['results'][0]['session_id']
        wire = deepcopy(observed[0]['history'])
        repair_message_sequence_with_cursor(children[0], wire)
        persisted = db.get_messages_as_conversation(sid)
        for rows in (wire, persisted):
            assert 'RECALLED_SECRET' not in json.dumps(rows)
            assert 'REQUEST_HOOK_INJECTION' not in json.dumps(rows)
            original_row = next(i for i, m in enumerate(rows) if m.get('content') == parent_request)
            assignment_row = next(i for i, m in enumerate(rows) if assignment in str(m.get('content')))
            assert assignment_row > original_row + 1
            assert rows[original_row + 1]['role'] == 'assistant'
            assert parent_request not in str(rows[assignment_row]['content'])
        assert [m['content'] for m in wire] == [m['content'] for m in persisted[:-1]]
        assert parent._session_messages == original
    finally:
        parent.close()


def test_resume_consumes_the_oneshot_activation_budget(harness, monkeypatch, delegate_task):
    monkeypatch.setattr('agent.oneshot_footprint.is_single_query_session', lambda: True)
    monkeypatch.setattr('tools.delegate_tool._get_oneshot_max_children', lambda: 1)
    make_parent, db, observed, _ = harness
    parent = make_parent()
    try:
        first = json.loads(delegate_task(tasks=[{'goal': 'First', 'fork_context': False}], parent_agent=parent))
        sid = first['results'][0]['session_id']
        for args in ({'tasks': [{'goal': 'Second'}]},
                     {'action': 'resume', 'session_id': sid, 'message': 'Continue'}):
            refused = json.loads(delegate_task(**args, parent_agent=parent))
            assert 'budget' in refused.get('error', '').lower(), refused
        assert len(observed) == 1
        assert json.loads(delegate_task(action='observe', session_id=sid, parent_agent=parent))['messages']
        assert json.loads(delegate_task(action='close', session_id=sid, parent_agent=parent))['status'] == 'closed'
    finally:
        parent.close()


@pytest.mark.parametrize('wedged', [True, False])
def test_timeout_never_reopens_a_session_with_a_live_worker(harness, monkeypatch, delegate_task, wedged):
    from run_agent import AIAgent
    from tools import delegate_tool_child_run as runner
    from tools.delegate_session_store import DelegateSessionStore

    make_parent, db, observed, _ = harness
    parent = make_parent()
    release, cleaned = threading.Event(), threading.Event()
    entered = []
    original_run = AIAgent.run_conversation
    original_close = runner._close_child

    def timed_out(child, **kwargs):
        entered.append(child.session_id)
        if wedged:
            assert release.wait(30)
            return original_run(child, **kwargs)
        raise TimeoutError('Provider timed out after its worker settled')

    def close(child, message):
        try:
            return original_close(child, message)
        finally:
            cleaned.set()

    monkeypatch.setattr(AIAgent, 'run_conversation', timed_out)
    monkeypatch.setattr(runner, '_close_child', close)
    monkeypatch.setattr('tools.delegate_tool._get_child_timeout', lambda: 2)
    try:
        result = json.loads(delegate_task(tasks=[{'goal': 'Bounded work', 'fork_context': False}], parent_agent=parent))
        entry = result['results'][0]
        assert entry['status'] == 'timeout', result
        sid = entry['session_id']
        store = DelegateSessionStore(db)
        if wedged:
            assert not cleaned.is_set()
            assert entry['session_status'] == 'closed'
            assert store.get(parent.session_id, sid)['status'] == 'closed'
            refused = json.loads(delegate_task(action='resume', session_id=sid, message='Unsafe retry', parent_agent=parent))
            assert 'closed' in refused.get('error', '').lower(), refused
            assert json.loads(delegate_task(action='close', session_id=sid, parent_agent=parent))['status'] == 'closed'
            assert len(entered) == 1
            release.set()
            assert cleaned.wait(20)
            # The Future's late release must not reopen the retired conversation.
            assert store.get(parent.session_id, sid)['status'] == 'closed'
            refused = json.loads(delegate_task(action='resume', session_id=sid, message='Retry after exit', parent_agent=parent))
            assert 'closed' in refused.get('error', '').lower(), refused
        else:
            assert cleaned.wait(10)
            assert store.get(parent.session_id, sid)['status'] == 'idle'
            monkeypatch.setattr(AIAgent, 'run_conversation', original_run)
            resumed = json.loads(delegate_task(action='resume', session_id=sid, message='Retry after exit', parent_agent=parent))
            assert resumed['results'][0]['status'] == 'completed', resumed
    finally:
        release.set()
        if entered:
            assert cleaned.wait(20)
        parent.close()


def test_runtime_plugin_uses_only_admitted_public_imports():
    from pathlib import Path
    from hermes_cli.plugin_validate_private_imports import private_import_findings
    assert private_import_findings(Path(__file__).parent) == []
