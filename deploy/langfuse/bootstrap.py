"""Provision a dedicated database/role and bucket on shared project services."""
import os

import boto3
from botocore.exceptions import ClientError
import psycopg2


def main():
    # libpq reads PGHOST/PGUSER/PGPASSWORD/PGDATABASE, without printing a DSN.
    connection = psycopg2.connect('')
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = 'ppt_langfuse'")
        if not cursor.fetchone():
            cursor.execute('CREATE ROLE ppt_langfuse LOGIN PASSWORD %s', (os.environ['LF_DATABASE_PASSWORD'],))
        cursor.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'langfuse'")
        owner = cursor.fetchone()
        if owner is None:
            cursor.execute('CREATE DATABASE langfuse OWNER ppt_langfuse')
        elif owner[0] != 'ppt_langfuse':
            raise RuntimeError('Existing langfuse database has a different owner; refusing to modify it')
    connection.close()
    probe = psycopg2.connect(host=os.environ['PGHOST'], dbname='langfuse', user='ppt_langfuse',
                             password=os.environ['LF_DATABASE_PASSWORD'])
    probe.close()
    s3 = boto3.client('s3', endpoint_url='http://minio:9000', region_name='us-east-1',
                     aws_access_key_id=os.environ['LF_S3_ACCESS_KEY_ID'],
                     aws_secret_access_key=os.environ['LF_S3_SECRET_ACCESS_KEY'])
    try:
        s3.head_bucket(Bucket='langfuse')
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('404', 'NoSuchBucket', 'NotFound'):
            raise
        s3.create_bucket(Bucket='langfuse')
    print('Langfuse database, dedicated role and shared-storage bucket are ready.')


if __name__ == '__main__':
    main()
