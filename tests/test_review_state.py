"""确认 .review_state.json 合法且可被 json.load，含标准字段。"""
import json
import os


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def test_review_state_is_valid_json():
    path = os.path.join(PROJECT_ROOT, '.review_state.json')
    assert os.path.exists(path), '.review_state.json 必须存在'
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert data.get('last_exported_sha') is None or isinstance(data['last_exported_sha'], str)
    assert data.get('last_exported_at') is None or isinstance(data['last_exported_at'], str)
    assert 'exports' in data
    assert isinstance(data['exports'], list)


def test_requirements_txt_lists_new_deps():
    path = os.path.join(PROJECT_ROOT, 'requirements.txt')
    assert os.path.exists(path)
    content = open(path).read()
    assert 'python-docx' in content
    assert 'lxml' in content
    assert 'latex2mathml' in content
    assert 'anthropic' in content
    assert 'pypinyin' in content
