import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / 'production-readiness-audit.n8n.json'

FORBIDDEN_NODE_TYPES = {
    'n8n-nodes-base.executeCommand',
    'n8n-nodes-base.readBinaryFile',
    'n8n-nodes-base.writeBinaryFile',
    'n8n-nodes-base.ssh',
    'n8n-nodes-base.localFileTrigger',
}

ALLOWED_CLOUD_NODE_TYPES = {
    'n8n-nodes-base.manualTrigger',
    'n8n-nodes-base.set',
    'n8n-nodes-base.code',
    'n8n-nodes-base.httpRequest',
}


def load_workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding='utf-8'))


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_strings(nested)


def test_workflow_top_level_shape_and_inactive_default():
    workflow = load_workflow()
    assert workflow['name'] == 'Production Readiness Audit'
    assert workflow['active'] is False
    assert isinstance(workflow['nodes'], list) and workflow['nodes']
    assert isinstance(workflow['connections'], dict)
    assert isinstance(workflow.get('settings'), dict)



def test_workflow_connections_reference_existing_nodes():
    workflow = load_workflow()
    node_names = {node['name'] for node in workflow['nodes']}
    for source_name, connection_groups in workflow['connections'].items():
        assert source_name in node_names
        for branch in connection_groups.get('main', []):
            for target in branch:
                assert target['node'] in node_names



def test_only_cloud_compatible_nodes_are_used():
    workflow = load_workflow()
    node_types = {node['type'] for node in workflow['nodes']}
    assert FORBIDDEN_NODE_TYPES.isdisjoint(node_types)
    assert node_types <= ALLOWED_CLOUD_NODE_TYPES



def test_runtime_inputs_require_owner_and_repo_without_hardcoded_repository_values():
    workflow = load_workflow()
    nodes = {node['name']: node for node in workflow['nodes']}
    runtime_inputs = nodes['Runtime Inputs']['parameters']['assignments']['assignments']
    values = {assignment['name']: assignment['value'] for assignment in runtime_inputs}
    assert values['owner'] == ''
    assert values['repo'] == ''
    assert values['writeReport'] is True
    assert values['openPr'] is False

    validate_code = nodes['Validate And Normalize']['parameters']['jsCode']
    assert "const owner = requireText('owner');" in validate_code
    assert "const repo = requireText('repo');" in validate_code
    assert 'enforceReadOnlyAgent: true' in validate_code
    assert 'audit/production-readiness-' in validate_code

    raw = WORKFLOW_PATH.read_text(encoding='utf-8')
    assert 'ebyron357' not in raw
    assert 'LABELOS' not in raw



def test_workflow_wires_single_repair_pass_and_final_failure():
    workflow = load_workflow()
    nodes = {node['name']: node for node in workflow['nodes']}
    required = {
        'Validate Initial Report',
        'Gate Needs Repair',
        'OpenAI Repair Report',
        'Validate Repaired Report',
        'Fail Repair Invalid',
    }
    assert required <= nodes.keys()
    names = [node['name'] for node in workflow['nodes']]
    assert names.count('OpenAI Repair Report') == 1

    connections = workflow['connections']
    repair_chain = [
        ('Validate Initial Report', 'Gate Needs Repair'),
        ('Gate Needs Repair', 'OpenAI Repair Report'),
        ('OpenAI Repair Report', 'Validate Repaired Report'),
        ('Validate Repaired Report', 'Fail Repair Invalid'),
    ]
    for source, target in repair_chain:
        targets = {
            edge['node']
            for branch in connections[source]['main']
            for edge in branch
        }
        assert target in targets



def test_report_write_and_pr_nodes_use_canonical_targets():
    workflow = load_workflow()
    nodes = {node['name']: node for node in workflow['nodes']}
    write_report = nodes['Write AUDIT_REPORT.md']['parameters']
    write_body = write_report['jsonBody']
    assert 'docs(audit): production readiness audit report' in write_body
    assert '/contents/AUDIT_REPORT.md' in write_report['url']

    create_pr = nodes['Create Pull Request']['parameters']['jsonBody']
    assert 'docs(audit): production readiness audit report' in create_pr
    assert 'Automated production-readiness audit and remediation plan.\\nNo application remediation was applied.' in create_pr



def test_no_embedded_secrets_and_expressions_are_plausible():
    workflow = load_workflow()
    raw = WORKFLOW_PATH.read_text(encoding='utf-8')
    secret_patterns = [
        r'ghp_[A-Za-z0-9]{20,}',
        r'github_pat_[A-Za-z0-9_]{20,}',
        r'sk-[A-Za-z0-9]{20,}',
        r'AKIA[0-9A-Z]{16}',
    ]
    for pattern in secret_patterns:
        assert re.search(pattern, raw) is None

    for string_value in iter_strings(workflow):
        if string_value.startswith('={{'):
            assert string_value.endswith('}}')
            assert string_value.count('{{') == string_value.count('}}')



def test_validation_logic_and_output_fields_are_present():
    workflow = load_workflow()
    nodes = {node['name']: node for node in workflow['nodes']}

    validate_code = nodes['Validate Initial Report']['parameters']['jsCode']
    assert '## Critical Findings' in validate_code
    assert '## High Priority Findings' in validate_code
    assert '## Medium Priority Findings' in validate_code
    assert '## Low Priority Findings' in validate_code
    assert 'Severity:' in validate_code
    assert 'Dependencies / Blockers:' in validate_code

    final_nodes = [
        nodes['Return Read Only Result']['parameters']['jsCode'],
        nodes['Finalize Written Result No PR']['parameters']['jsCode'],
        nodes['Finalize Written Result With PR']['parameters']['jsCode'],
    ]
    for code in final_nodes:
        for field in [
            'audit_completed',
            'effective_branch',
            'audit_branch',
            'baseline_sha',
            'audit_commit_sha',
            'severity_counts',
            'primary_shipment_blockers',
            'validation_results',
            'production_dependencies',
            'report_structure_valid',
            'finding_remediation_validation_passed',
            'unexpected_file_changes',
            'pr_created',
            'pr_url',
        ]:
            assert field in code
