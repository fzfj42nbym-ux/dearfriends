#!/usr/bin/env python3
"""Exercise messenger creation and RLS against an isolated PostgreSQL 16 database.

Run from the repository root (the schema path is independent of working directory):
    python3 tests/check_messenger_sql.py
    python3 tests/check_messenger_sql.py --json-out /tmp/messenger-sql-results.json

Requires Python 3 and Docker CLI access to a local Unix-socket daemon. The official
postgres:16 image is pulled if it is not cached. Registry/proxy authentication is
left to the existing Docker configuration. No Supabase credentials are used.

The selected Docker context/DOCKER_HOST is resolved locally, and TCP/SSH endpoints
are rejected before connecting to any daemon. Commands are then pinned to that
Unix socket; inherited endpoint/TLS selectors cannot redirect later commands.
A unique labelled container runs with --network none, no published ports or host
volumes, and local trust authentication. Only this test container is removed in
finally, including on a failing SQL assertion. All data consists of test fixtures.
"""

import argparse
import concurrent.futures
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from urllib.parse import urlsplit
import uuid


def local_docker():
    """Honor the selected local endpoint without contacting a remote daemon."""
    executable = shutil.which('docker')
    if executable is None:
        raise RuntimeError('Docker CLI is required for SQL regression checks')
    docker_env = dict(os.environ)
    context = docker_env.get('DOCKER_CONTEXT')
    if not context and docker_env.get('DOCKER_HOST'):
        endpoint = docker_env['DOCKER_HOST']
    else:
        command = [executable, 'context', 'inspect']
        if context:
            command.append(context)
        command += ['--format', '{{ (index .Endpoints "docker").Host }}']
        inspected = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if inspected.returncode:
            raise RuntimeError('Cannot resolve the selected Docker context; select a local Unix socket with DOCKER_HOST')
        endpoint = inspected.stdout.strip()
    selected = urlsplit(endpoint)
    if selected.scheme != 'unix' or selected.netloc or not selected.path.startswith('/'):
        raise RuntimeError('Only local Unix-socket Docker daemons are allowed; TCP/SSH endpoints are refused')
    try:
        if not stat.S_ISSOCK(Path(selected.path).stat().st_mode):
            raise RuntimeError('Selected Docker endpoint is not a Unix socket')
    except OSError as error:
        raise RuntimeError('Selected local Docker socket is unavailable') from error

    # Selection has already been honored and checked above. Pin this exact socket
    # so context/TLS environment selectors cannot redirect these child commands.
    # DOCKER_CONFIG and registry credential/proxy settings remain untouched.
    for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        docker_env.pop(name, None)
    docker = [executable, '--host=' + endpoint]
    healthy = subprocess.run(docker + ['info', '--format', '{{.ServerVersion}}'],
                             env=docker_env, capture_output=True, text=True, timeout=15)
    if healthy.returncode:
        raise RuntimeError('Selected local Docker daemon is unavailable: ' + healthy.stderr.strip())
    return docker, docker_env


@contextmanager
def postgres_container(docker, docker_env):
    run_id = uuid.uuid4().hex
    name = 'dearfriends-sql-test-' + run_id[:12]
    label = 'dearfriends.sql-test'
    try:
        started = subprocess.run(docker + [
            'run', '--rm', '-d', '--name', name,
            '--label', label + '=' + run_id,
            '--network', 'none',
            '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
            '-e', 'POSTGRES_DB=messenger_test',
            'postgres:16', '-c', 'wal_level=logical',
        ], env=docker_env, capture_output=True, text=True, timeout=180)
        if started.returncode:
            raise RuntimeError('Cannot start isolated PostgreSQL: ' + started.stderr.strip())

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            logs = subprocess.run(docker + ['logs', name], env=docker_env,
                                  capture_output=True, text=True, timeout=10)
            # Wait past the temporary initdb server before checking the final one.
            if 'PostgreSQL init process complete; ready for start up.' in logs.stdout + logs.stderr:
                ready = subprocess.run(docker + ['exec', name, 'pg_isready', '-U', 'postgres', '-d', 'messenger_test'],
                                       env=docker_env, capture_output=True, timeout=10)
                if ready.returncode == 0:
                    break
            time.sleep(.1)
        else:
            raise RuntimeError('Local PostgreSQL did not become ready: ' + logs.stdout + logs.stderr)

        psql = docker + ['exec', '-i', name, 'psql', '-U', 'postgres', '-d', 'messenger_test',
                         '-X', '-A', '-t', '-q', '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose']
        yield psql
    finally:
        # UUID name plus an ownership label prevents cleanup of another process's
        # container, even if startup failed before docker run returned an ID.
        owned = subprocess.run(docker + ['container', 'inspect', name, '--format',
                                         '{{ index .Config.Labels "' + label + '" }}'],
                               env=docker_env, capture_output=True, text=True, timeout=10)
        if owned.returncode == 0:
            if owned.stdout.strip() != run_id:
                raise RuntimeError('Refusing to remove a container with another ownership label')
            removed = subprocess.run(docker + ['container', 'rm', '-f', name],
                                     env=docker_env, capture_output=True, text=True, timeout=15)
            if removed.returncode:
                raise RuntimeError('Could not remove this test container: ' + removed.stderr.strip())


def run_checks(psql, docker_env):
    passed = []

    def sql(source, role=None, email=None, expected_error=None):
        prefix = ''
        if role:
            prefix += 'set role ' + role + ';\n'
        if email is not None:
            prefix += "set request.jwt.claims = '" + json.dumps({'email': email}).replace("'", "''") + "';\n"
        result = subprocess.run(psql, input=prefix + source, text=True, capture_output=True, env=docker_env, timeout=30)
        if expected_error:
            assert result.returncode != 0, ('Expected SQL error', expected_error, source, result.stdout)
            assert expected_error in result.stderr, (expected_error, result.stderr)
        else:
            assert result.returncode == 0, (source, result.stdout, result.stderr)
        return result.stdout.strip()

    def check(name, source, **kwargs):
        value = sql(source, **kwargs)
        passed.append(name)
        return value

    def expect_count(source, count, **kwargs):
        assert sql(source, **kwargs) == str(count), source

    sql('''
    create role anon;
    create role authenticated;
    create schema auth;
    create function auth.jwt() returns jsonb language sql stable as $$
      select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb
    $$;
    create schema storage;
    create table storage.buckets (id text primary key, name text, public boolean);
    create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text);
    alter table storage.objects enable row level security;
    create publication supabase_realtime;
    grant usage on schema public, auth, storage to anon, authenticated;
    alter default privileges for role postgres in schema public grant all on tables to anon, authenticated;
    alter default privileges for role postgres in schema public grant usage on sequences to anon, authenticated;
    ''')
    schema = (Path(__file__).resolve().parents[1] / 'supabase' / 'schema.sql').read_text()
    check('full schema loads', schema)
    check('full schema can be rerun', schema)
    sql('''insert into public.members(email,name) values
    ('alice@example.com','Алиса'),('bella@example.com','Белла'),
    ('cara@example.com','Кара'),('dima@example.com','Дима'),
    ('eve@example.com','Ева'),('fred@example.com','Федя');''')

    auth = {'role': 'authenticated', 'email': 'alice@example.com'}
    check('anon cannot execute RPC', "select public.create_conversation('dm',null,array['bella@example.com']);", role='anon', email='alice@example.com', expected_error='42501')
    check('nonmember cannot create', "select public.create_conversation('dm',null,array['bella@example.com']);", role='authenticated', email='outsider@example.com', expected_error='42501')
    check('missing identity cannot create', "select public.create_conversation('dm',null,array['bella@example.com']);", role='authenticated', email='', expected_error='42501')

    invalid = [
        ('unknown kind', "select public.create_conversation('other',null,array['bella@example.com']);"),
        ('null kind', "select public.create_conversation(null,null,array['bella@example.com']);"),
        ('self-only DM', "select public.create_conversation('dm',null,array['alice@example.com']);"),
        ('too many DM participants', "select public.create_conversation('dm',null,array['bella@example.com','cara@example.com']);"),
        ('null participant', "select public.create_conversation('dm',null,array[null::text]);"),
        ('empty participant', "select public.create_conversation('dm',null,array['  ']);"),
        ('nonmember participant', "select public.create_conversation('dm',null,array['outsider@example.com']);"),
        ('blank group title', "select public.create_conversation('group','  ',array['bella@example.com']);"),
        ('long group title', "select public.create_conversation('group',repeat('я',81),array['bella@example.com']);"),
        ('self-only group', "select public.create_conversation('group','Группа',array['alice@example.com']);"),
        ('missing participants', "select public.create_conversation('dm');"),
        ('null participants', "select public.create_conversation('dm',null,null);"),
        ('oversized participant list', "select public.create_conversation('group','Группа',array_fill('bella@example.com'::text,array[100]));"),
    ]
    for name, source in invalid:
        check(name + ' rejected', source, expected_error='22023', **auth)
    expect_count('select count(*) from public.conversations;',0)
    passed.append('invalid calls leave no orphan conversations')

    dm = check('DM creates normalized caller and peer', "select public.create_conversation('dm',null,array['  BELLA@EXAMPLE.COM  ','bella@example.com']);", **auth)
    assert re.fullmatch(r'[0-9a-f-]{36}',dm),dm
    expect_count("select count(*) from public.conversations where id='"+dm+"' and kind='dm' and title is null and created_by='alice@example.com' and pair_key='alice@example.com|bella@example.com';",1)
    assert sql("select string_agg(email,',' order by email) from public.conversation_members where conversation_id='"+dm+"';") == 'alice@example.com,bella@example.com'
    same = check('reverse DM call reuses same conversation', "select public.create_conversation('dm',null,array['alice@example.com']);",role='authenticated',email='bella@example.com')
    assert same == dm
    same = check('uppercase authenticated identity reuses same DM', "select public.create_conversation('dm',null,array['bella@example.com']);",role='authenticated',email='ALICE@EXAMPLE.COM')
    assert same == dm

    group = check('group creates all members and trims title', "select public.create_conversation('group','  Вылазка  ',array['bella@example.com','cara@example.com','BELLA@example.com']);",**auth)
    expect_count("select count(*) from public.conversations where id='"+group+"' and kind='group' and title='Вылазка' and pair_key is null;",1)
    expect_count("select count(*) from public.conversation_members where conversation_id='"+group+"';",3)
    expect_count('select count(*) from public.conversations;',2,**auth)
    expect_count('select count(*) from public.conversation_members;',5,**auth)
    passed.append('creator can read both created conversations and memberships')

    foreign = {'role':'authenticated','email':'dima@example.com'}
    expect_count('select count(*) from public.conversations;',0,**foreign)
    expect_count('select count(*) from public.conversation_members;',0,**foreign)
    passed.append('other club member cannot read foreign conversations or memberships')
    check('direct conversation insert denied', "insert into public.conversations(kind,created_by,pair_key) values('dm','dima@example.com','forged');",expected_error='42501',**foreign)
    check('foreign membership insert denied',"insert into public.conversation_members(conversation_id,email) values('"+dm+"','dima@example.com');",expected_error='42501',**foreign)
    check('participant cannot directly add a foreign member',"insert into public.conversation_members(conversation_id,email) values('"+dm+"','dima@example.com');",expected_error='42501',**auth)
    check('DM participants can send messages',"insert into public.messages(conversation_id,author_email,author_name,text) values('"+dm+"','bella@example.com','Белла','Привет');",role='authenticated',email='bella@example.com')
    expect_count('select count(*) from public.messages;',1,**auth)
    expect_count('select count(*) from public.messages;',0,**foreign)
    passed.append('message read remains participant-only')
    check('foreign member cannot send to private conversation',"insert into public.messages(conversation_id,author_email,author_name,text) values('"+dm+"','dima@example.com','Дима','Недоступно');",expected_error='42501',**foreign)
    check('participant cannot spoof another message author',"insert into public.messages(conversation_id,author_email,author_name,text) values('"+dm+"','bella@example.com','Белла','Подмена');",expected_error='42501',**auth)

    sql("delete from public.members where email='bella@example.com';")
    expect_count('select count(*) from public.conversations;',0,role='authenticated',email='bella@example.com')
    check('offboarded member cannot reuse RPC',"select public.create_conversation('dm',null,array['alice@example.com']);",role='authenticated',email='bella@example.com',expected_error='42501')
    sql("insert into public.members(email,name) values('bella@example.com','Белла');")

    # An artificial database failure AFTER conversation insertion must roll it back.
    sql('''create function public.test_fail_membership() returns trigger language plpgsql as $$
    begin if new.email='cara@example.com' then raise exception 'test membership failure'; end if; return new; end;
    $$;
    create trigger test_fail_membership before insert on public.conversation_members for each row execute function public.test_fail_membership();''')
    before = sql('select count(*) from public.conversations;')
    check('membership failure rejects whole creation',"select public.create_conversation('group','Не сохранять',array['cara@example.com']);",expected_error='P0001',**auth)
    assert sql('select count(*) from public.conversations;') == before
    passed.append('membership insertion failure rolls conversation back atomically')
    sql('drop trigger test_fail_membership on public.conversation_members; drop function public.test_fail_membership();')

    def racing_dm(pair):
        return sql("select public.create_conversation('dm',null,array['"+pair[1]+"']);",role='authenticated',email=pair[0])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        race_ids=list(pool.map(racing_dm,[('eve@example.com','fred@example.com'),('fred@example.com','eve@example.com')]))
    assert race_ids[0] == race_ids[1], race_ids
    expect_count("select count(*) from public.conversations where pair_key='eve@example.com|fred@example.com';",1)
    expect_count("select count(*) from public.conversation_members where conversation_id='"+race_ids[0]+"';",2)
    passed.append('concurrent opposite DM calls return one conversation with two members')

    # A former participant cannot silently rejoin via a deterministic DM key.
    sql("delete from public.conversation_members where conversation_id='"+dm+"' and email='bella@example.com';",role='authenticated',email='bella@example.com')
    check('departed participant cannot rejoin existing DM',"select public.create_conversation('dm',null,array['alice@example.com']);",role='authenticated',email='bella@example.com',expected_error='42501')
    check('mismatched existing DM does not add members',"select public.create_conversation('dm',null,array['bella@example.com']);",expected_error='42501',**auth)

    assert sql("select has_function_privilege('anon','public.create_conversation(text,text,text[])','execute');") == 'f'
    assert sql("select has_function_privilege('authenticated','public.create_conversation(text,text,text[])','execute');") == 't'
    assert sql("select proconfig::text from pg_proc where oid='public.create_conversation(text,text,text[])'::regprocedure;") == '{"search_path=\\"\\""}'
    passed.append('RPC privileges and empty search_path are hardened')

    check('schema rerun preserves existing conversations and permissions',schema)
    expect_count('select count(*) from public.conversations;',3)
    return {'passed': len(passed), 'checks': passed, 'postgres': sql('select version();')}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json-out', type=Path, help='Optional JSON result file; no file is written by default')
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run without Python -O so regression assertions remain enabled')
    docker, docker_env = local_docker()
    with postgres_container(docker, docker_env) as psql:
        result = run_checks(psql, docker_env)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json_out:
        args.json_out.write_text(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
