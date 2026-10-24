#!/usr/bin/env python3
"""Exercise the imported club features and their RLS in isolated PostgreSQL.

Run: python3 -B tests/check_club_features_sql.py
Uses the existing local-only Docker harness: a uniquely owned postgres:16
container, no network, ports, host volumes, or production Supabase credentials.
"""

import argparse
import json
from pathlib import Path
import subprocess

from check_messenger_sql import local_docker, postgres_container


def run_checks(psql, docker_env):
    passed = []

    def sql(source, role=None, email=None, expected_error=None):
        prefix = ''
        if role:
            prefix += 'set role ' + role + ';\n'
        if email is not None:
            claims = json.dumps({'email': email}).replace("'", "''")
            prefix += "set request.jwt.claims = '" + claims + "';\n"
        result = subprocess.run(psql, input=prefix + source, text=True,
                                capture_output=True, env=docker_env, timeout=30)
        if expected_error:
            codes = (expected_error,) if isinstance(expected_error, str) else expected_error
            assert result.returncode != 0, (codes, source, result.stdout)
            assert any(code in result.stderr for code in codes), (codes, result.stderr)
        else:
            assert result.returncode == 0, (source, result.stdout, result.stderr)
        return result.stdout.strip()

    def check(name, source, **kwargs):
        result = sql(source, **kwargs)
        passed.append(name)
        return result

    def count(source, expected, **kwargs):
        assert sql(source, **kwargs) == str(expected), source

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
    schema = (Path(__file__).resolve().parents[1] / 'supabase/schema.sql').read_text()
    check('full schema loads on a fresh database', schema)
    check('empty schema is rerunnable', schema)
    sql("""insert into public.members(email,name,char) values
      ('alice@example.com','Алиса','alice'),
      ('bella@example.com','Белла','kira'),
      ('cara@example.com','Кара','natasha');""")
    alice = {'role': 'authenticated', 'email': 'alice@example.com'}
    uppercase_alice = {'role': 'authenticated', 'email': 'ALICE@EXAMPLE.COM'}
    bella = {'role': 'authenticated', 'email': 'bella@example.com'}
    outsider = {'role': 'authenticated', 'email': 'outsider@example.com'}

    check('member can update own birthday with uppercase authenticated identity',
          "update public.members set birthday='1990-02-28' where email='alice@example.com';",
          **uppercase_alice)
    count("select count(*) from public.members where email='alice@example.com' and birthday='1990-02-28';", 1)
    check('member can clear own birthday',
          "update public.members set birthday=null where email='alice@example.com';", **alice)
    count("select count(*) from public.members where email='alice@example.com' and birthday is null;", 1)
    for column, value in (('name', "'Подмена'"), ('email', "'other@example.com'"),
                          ('char', "'vova'"), ('created_at', "now()")):
        check('birthday grant cannot update member ' + column,
              f"update public.members set {column}={value} where email='alice@example.com';",
              expected_error='42501', **alice)
    sql("update public.members set birthday='2000-01-01' where email='bella@example.com';", **alice)
    count("select count(*) from public.members where email='bella@example.com' and birthday is null;", 1)
    passed.append('member cannot change another birthday')

    challenge = check('member creates own challenge',
                      "insert into public.challenges(title,text,until,by) values "
                      "('Прогулка','Встречаемся в парке',current_date,'alice@example.com') returning id;", **alice)
    check('member joins challenge under their own email',
          f"insert into public.challenge_join(challenge_id,email) values ({challenge},'bella@example.com');", **bella)
    check('join primary key rejects duplicate participation',
          f"insert into public.challenge_join(challenge_id,email) values ({challenge},'bella@example.com');",
          expected_error='23505', **bella)
    check('challenge join rejects a nonexistent challenge',
          "insert into public.challenge_join(challenge_id,email) values (9999999,'alice@example.com');",
          expected_error='23503', **alice)
    check('member can withdraw own participation',
          f"delete from public.challenge_join where challenge_id={challenge} and email='bella@example.com';", **bella)
    count('select count(*) from public.challenge_join;', 0)
    sql(f"insert into public.challenge_join(challenge_id,email) values ({challenge},'bella@example.com');", **bella)
    sql(f"delete from public.challenge_join where challenge_id={challenge};", **alice)
    count('select count(*) from public.challenge_join;', 1)
    passed.append('creator cannot remove another participant directly')

    fund = check('member records a positive contribution',
                 "insert into public.fund(amount,note,by) values (100.25,'На встречу','alice@example.com') returning id;", **uppercase_alice)
    receipt = check('member records a positive receipt with a private object path',
                    "insert into public.receipts(amount,note,path,by) values "
                    "(75.50,'Чай','receipts/test-image.webp','alice@example.com') returning id;", **alice)
    for table in ('challenges', 'challenge_join', 'receipts', 'fund'):
        count('select count(*) from public.' + table + ';', 1, **bella)
        check('anonymous cannot read ' + table,
              'select * from public.' + table + ';', role='anon',
              email='alice@example.com', expected_error='42501')
        count('select count(*) from public.' + table + ';', 0, **outsider)
    passed.append('club features are visible to members and hidden from authenticated outsiders')

    inserts = {
        'challenges': "insert into public.challenges(title,by) values ('Подмена','bella@example.com');",
        'challenge_join': f"insert into public.challenge_join(challenge_id,email) values ({challenge},'cara@example.com');",
        'receipts': "insert into public.receipts(amount,by) values (12.34,'bella@example.com');",
        'fund': "insert into public.fund(amount,by) values (12.34,'bella@example.com');",
    }
    for table, statement in inserts.items():
        check('member cannot forge owner in ' + table, statement, expected_error='42501', **alice)
    for table in ('fund', 'receipts'):
        for label, value in (('zero', '0'), ('negative', '-1'), ('not-a-number', "'NaN'::numeric")):
            check(table + ' rejects new ' + label + ' amount',
                  f"insert into public.{table}(amount,by) values ({value},'alice@example.com');",
                  expected_error=('42501', '23514'), **alice)
    for table, statement in {
        'fund': "insert into public.fund(amount,by) values (1,'outsider@example.com');",
        'receipts': "insert into public.receipts(amount,by) values (1,'outsider@example.com');",
        'challenges': "insert into public.challenges(title,by) values ('Нет доступа','outsider@example.com');",
        'challenge_join': f"insert into public.challenge_join(challenge_id,email) values ({challenge},'outsider@example.com');",
    }.items():
        check('outsider cannot insert into ' + table, statement, expected_error='42501', **outsider)
    for table, column, value in (('challenges', 'title', "'Изменено'"), ('challenge_join', 'email', "'cara@example.com'"),
                                 ('fund', 'amount', '200'), ('receipts', 'amount', '200')):
        check('table update is not granted for ' + table,
              f'update public.{table} set {column}={value};', expected_error='42501', **alice)

    for table, row_id in (('fund', fund), ('receipts', receipt), ('challenges', challenge)):
        sql(f'delete from public.{table} where id={row_id};', **bella)
        count(f'select count(*) from public.{table} where id={row_id};', 1)
    passed.append('another member cannot delete recorded contributions, receipts or challenges')
    check('creator can delete own challenge', f'delete from public.challenges where id={challenge};', **alice)
    count('select count(*) from public.challenge_join;', 0)
    passed.append('deleting a challenge cascades participation')
    disposable_fund = sql("insert into public.fund(amount,by) values (2,'alice@example.com') returning id;", **alice)
    disposable_receipt = sql("insert into public.receipts(amount,by) values (2,'alice@example.com') returning id;", **alice)
    check('member can delete their contribution', f'delete from public.fund where id={disposable_fund};', **uppercase_alice)
    check('member can delete their receipt', f'delete from public.receipts where id={disposable_receipt};', **alice)
    count(f'select count(*) from public.fund where id={disposable_fund};', 0)
    count(f'select count(*) from public.receipts where id={disposable_receipt};', 0)

    preserved_challenge = sql("insert into public.challenges(title,by) values ('Существующий вызов','alice@example.com') returning id;", **alice)
    sql(f"insert into public.challenge_join(challenge_id,email) values ({preserved_challenge},'bella@example.com');", **bella)
    # Simulate an already-installed upstream version with its permissive policies.
    sql('''
    drop policy "fund add" on public.fund;
    create policy "fund add" on public.fund for insert to authenticated with check (public.is_member());
    drop policy "fund del own" on public.fund;
    create policy "fund del own" on public.fund for delete to authenticated using (true);
    drop policy "rc add" on public.receipts;
    create policy "rc add" on public.receipts for insert to authenticated with check (public.is_member());
    drop policy "chal add" on public.challenges;
    create policy "chal add" on public.challenges for insert to authenticated with check (public.is_member());
    drop policy "cjoin add" on public.challenge_join;
    create policy "cjoin add" on public.challenge_join for insert to authenticated with check (public.is_member());
    grant all on public.fund,public.receipts,public.challenges,public.challenge_join to anon,authenticated;
    grant update on public.members to authenticated;
    ''')
    legacy = sql("insert into public.fund(amount,note,by) values (-12.50,'Существующая трата','bella@example.com') returning id;")
    check('upgrade replaces permissive policies without deleting legacy data', schema)
    count(f'select count(*) from public.fund where id={legacy} and amount=-12.50;', 1, **alice)
    count(f'select count(*) from public.fund where id={fund} and amount=100.25;', 1, **alice)
    count(f'select count(*) from public.receipts where id={receipt} and amount=75.50;', 1, **alice)
    count(f'select count(*) from public.challenges where id={preserved_challenge};', 1, **alice)
    count(f'select count(*) from public.challenge_join where challenge_id={preserved_challenge};', 1, **alice)
    for table in ('fund', 'receipts', 'challenges'):
        check('upgrade rejects forged owner in ' + table, inserts[table], expected_error='42501', **alice)
    check('upgrade rejects forged challenge participation',
          f"insert into public.challenge_join(challenge_id,email) values ({preserved_challenge},'cara@example.com');",
          expected_error='42501', **alice)
    sql(f'delete from public.fund where id={fund};', **bella)
    count(f'select count(*) from public.fund where id={fund};', 1)
    passed.append('upgrade removes permissive legacy deletion policy')
    check('upgrade removes legacy broad member update grant',
          "update public.members set name='Подмена' where email='alice@example.com';", expected_error='42501', **alice)
    check('populated upgraded schema remains rerunnable', schema)
    count(f'select count(*) from public.fund where id={legacy} and amount=-12.50;', 1)

    sql("delete from public.members where email='alice@example.com';")
    for table in ('fund', 'receipts', 'challenges', 'challenge_join'):
        count('select count(*) from public.' + table + ';', 0, **alice)
    check('offboarded member cannot record a contribution',
          "insert into public.fund(amount,by) values (1,'alice@example.com');", expected_error='42501', **alice)
    for table, row_id in (('fund', fund), ('receipts', receipt)):
        sql(f'delete from public.{table} where id={row_id};', **alice)
        count(f'select count(*) from public.{table} where id={row_id};', 1)
    passed.append('offboarding blocks old reads, inserts and own-row deletion')
    assert sql("select public from storage.buckets where id='photos';") == 'f'
    passed.append('receipt images remain in a private bucket')
    count("select count(*) from pg_publication_tables where pubname='supabase_realtime' "
          "and schemaname='public' and tablename in ('members','challenges','challenge_join','receipts','fund');", 5)
    passed.append('birthday members and all four feature tables are published once for realtime')
    return {'passed': len(passed), 'checks': passed, 'postgres': sql('select version();')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run without -O so SQL assertions remain enabled')
    docker, docker_env = local_docker()
    with postgres_container(docker, docker_env) as psql:
        result = run_checks(psql, docker_env)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json_out:
        args.json_out.write_text(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
