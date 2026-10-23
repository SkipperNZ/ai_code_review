import pytest

from aicr import evaluation
from aicr.io import write_json


@pytest.mark.parametrize('count,expected_p95', [(20, 19), (40, 38)])
def test_report_uses_nearest_rank_p95(tmp_path, monkeypatch, count, expected_p95):
    selected = [f's{i}' for i in range(1, count + 1)]
    write_json(tmp_path / 'manifest.json', {
        'id': 'latency-fixture', 'selected': selected, 'modes': ['local'], 'config': {},
    })
    rows = [{'sample_id': sid, 'mode': 'local', 'status': 'json_invalid', 'wall_seconds': i,
             'strict_eligible': False} for i, sid in enumerate(selected, 1)]
    monkeypatch.setattr(evaluation, 'latest_results', lambda _: rows)
    metrics = evaluation.evaluate(tmp_path)
    assert metrics['latency_quantile_method'] == 'nearest_rank'
    assert metrics['modes']['local']['p95_seconds'] == expected_p95
    assert metrics['modes']['local']['p50_seconds'] == (count + 1) / 2
    assert metrics['modes']['local']['statuses'] == {'json_invalid': count}
