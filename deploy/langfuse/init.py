"""Create local secrets once and connect the existing application's environment.

Run with Python 3.10+. Never prints secrets; existing generated values are retained.
"""
from pathlib import Path
import secrets


def read_env(path):
    return dict(line.split('=', 1) for line in path.read_text(encoding='utf-8-sig').splitlines()
                if line and not line.startswith('#') and '=' in line)


def main():
    here = Path(__file__).resolve().parent
    local = here / '.env'
    if not local.exists():
        values = {key: secrets.token_hex(32) for key in (
            'POSTGRES_PASSWORD', 'SALT', 'ENCRYPTION_KEY', 'CLICKHOUSE_PASSWORD',
            'REDIS_AUTH', 'MINIO_PASSWORD', 'NEXTAUTH_SECRET', 'ADMIN_PASSWORD',
            'METRICS_ACCESS_TOKEN')}
        values['LANGFUSE_PUBLIC_KEY'] = 'pk-lf-' + secrets.token_hex(16)
        values['LANGFUSE_SECRET_KEY'] = 'sk-lf-' + secrets.token_hex(32)
        with local.open('x', encoding='utf-8') as stream:
            stream.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    values = read_env(local)
    app_env = here.parent / '.env'
    if not app_env.exists():
        raise SystemExit('Create deploy/.env from .env.example and configure model credentials first.')
    updates = {
        'LANGFUSE_ENABLED': 'true', 'LANGFUSE_BASE_URL': 'http://langfuse-web:3000',
        'LANGFUSE_UI_URL': 'http://localhost:3000', 'LANGFUSE_PROJECT_ID': 'ppt-local-project',
        'LANGFUSE_PUBLIC_KEY': values['LANGFUSE_PUBLIC_KEY'],
        'LANGFUSE_SECRET_KEY': values['LANGFUSE_SECRET_KEY'],
        'METRICS_ACCESS_TOKEN': values['METRICS_ACCESS_TOKEN'],
        'LANGFUSE_CAPTURE_CONTENT': 'false',
    }
    lines = app_env.read_text(encoding='utf-8-sig').splitlines()
    lines = [line for line in lines if line.split('=', 1)[0].strip() not in updates]
    app_env.write_text('\n'.join(lines) + '\n' + ''.join(f'{k}={v}\n' for k, v in updates.items()), encoding='utf-8')
    print('Local secrets ready; deploy/.env observability settings updated. No secrets printed.')


if __name__ == '__main__':
    main()
