"""Observe keeps host-supplied tool context through native plugin dispatch."""
import json


def test_observe_tool_history_through_plugin(harness):
    from tools.registry import registry
    make_parent, db, _, _ = harness
    parent = make_parent()
    try:
        dispatch = registry.get_entry('delegate_task').handler
        spawned = json.loads(dispatch({'tasks': [{'goal': 'Inspect', 'fork_context': False}]},
                                      parent_agent=parent))
        sid = spawned['results'][0]['session_id']
        db.append_message(sid, 'assistant', '', tool_calls=[{
            'type': 'function', 'id': 'write-design', 'function': {
                'name': 'write_file', 'arguments': json.dumps({'path': '/project/DESIGN.md', 'content': 'text'})}}])
        db.append_message(sid, 'tool', 'HEADER\n' + 'x' * 10000 + '\nSUCCESS', tool_name='write_file',
                          tool_call_id='write-design')
        result = json.loads(dispatch({'action': 'observe', 'session_id': sid, 'limit': 20}, parent_agent=parent))
        call, output = result['messages'][-2:]
        assert call['tool_calls'] == [{'name': 'write_file', 'target': '/project/DESIGN.md'}]
        assert output['tool_name'] == 'write_file'
        assert output['content'].startswith('HEADER\n')
        assert output['content'].endswith('\nSUCCESS')
        assert len(output['content']) <= 1500
        assert result['truncated']
    finally:
        parent.close()
