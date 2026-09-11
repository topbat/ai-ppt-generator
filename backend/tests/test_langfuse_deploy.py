"""Initialization must preserve model configuration and never rotate existing keys."""
from pathlib import Path
import subprocess
import sys


def test_init_is_idempotent_and_does_not_print_secrets(tmp_path):
    source = Path(__file__).resolve().parents[2] / 'deploy' / 'langfuse' / 'init.py'
    folder = tmp_path / 'deploy' / 'langfuse'
    folder.mkdir(parents=True)
    script = folder / 'init.py'
    script.write_bytes(source.read_bytes())
    app = folder.parent / '.env'
    app.write_text('# retained\nQWEN_API_KEY=model-secret\nLANGFUSE_ENABLED=false\n', encoding='utf-8')
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    secret_file = folder / '.env'
    secrets_before = secret_file.read_bytes()
    app_before = app.read_bytes()
    subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
    assert secret_file.read_bytes() == secrets_before
    assert app.read_bytes() == app_before
    body = app.read_text(encoding='utf-8')
    assert '# retained\nQWEN_API_KEY=model-secret\n' in body
    assert body.count('LANGFUSE_ENABLED=') == 1
    assert 'LANGFUSE_ENABLED=true' in body
    assert 'LANGFUSE_CAPTURE_CONTENT=false' in body
    assert 'model-secret' not in first.stdout
    for line in secrets_before.decode().splitlines():
        assert line.split('=', 1)[1] not in first.stdout


def test_compose_reuses_project_dependencies_without_extra_network():
    import yaml
    root = Path(__file__).resolve().parents[2]
    base = yaml.safe_load((root/'deploy/docker-compose.yml').read_text(encoding='utf-8'))
    extra = yaml.safe_load((root/'deploy/docker-compose.langfuse.yml').read_text(encoding='utf-8'))
    assert base['name'] == 'ppt-generator' and 'name' not in extra
    assert not {'redis', 'minio', 'postgres'} & extra['services'].keys()
    assert 'networks' not in extra
    for key in ('langfuse-web', 'langfuse-worker'):
        env = extra['services'][key]['environment']
        assert env['HOSTNAME'] == '0.0.0.0'
        assert env['REDIS_CONNECTION_STRING'] == 'redis://redis:6379/4'
        assert 'REDIS_AUTH' not in env
        assert env['LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT'] == 'http://minio:9000'
        assert env['LANGFUSE_S3_EVENT_UPLOAD_BUCKET'] == 'langfuse'
        assert '@postgres:5432/langfuse' in env['DATABASE_URL']
    assert 'ports' not in extra['services']['clickhouse']
    assert extra['services']['langfuse-web']['environment']['HOSTNAME'] == '0.0.0.0'
