#!/usr/bin/env python3
"""Exercise library validation, ratings, private reads and atomic loans in Postgres.

Run: python3 -B tests/check_library_sql.py
Reuses the local-only Docker harness from check_messenger_sql.py: a unique owned
postgres:16 container, --network none, no ports/volumes, no Supabase credentials.
Checks cover fresh installs, reruns and upgrades from the populated three-kind
schema. Existing catalog rows, ratings and outstanding loans must survive.
"""

import argparse
import concurrent.futures
import json
from pathlib import Path
import re
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
            assert result.returncode != 0, (expected_error, source, result.stdout)
            assert expected_error in result.stderr, (expected_error, result.stderr)
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
    check('full schema loads', schema)
    check('empty schema is rerunnable', schema)
    sql("""insert into public.members(email,name) values
      ('alice@example.com','Алиса'),('bella@example.com','Белла'),
      ('cara@example.com','Кара'),('departed@example.com','Бывший участник');""")
    alice = {'role': 'authenticated', 'email': 'alice@example.com'}
    bella = {'role': 'authenticated', 'email': 'bella@example.com'}
    cara = {'role': 'authenticated', 'email': 'cara@example.com'}
    outsider = {'role': 'authenticated', 'email': 'outsider@example.com'}

    book = check('member can add and read own shareable book',
                 "insert into public.library_items(kind,title,creator,added_by,shareable) values ('book','Пикник на обочине','Стругацкие','alice@example.com',true) returning id;", **alice)
    assert re.fullmatch(r'[0-9a-f-]{36}', book), book
    game = check('member can add shareable game with time and players',
                 "insert into public.library_items(kind,title,added_by,shareable,duration_minutes,players_min,players_max) values ('game','Каркассон','alice@example.com',true,45,2,5) returning id;", **alice)
    film = check('member can add film without a physical copy',
                 "insert into public.library_items(kind,title,added_by,duration_minutes) values ('movie','Амели','alice@example.com',122) returning id;", **alice)
    count('select count(*) from public.library_items;', 3, **bella)
    passed.append('other active member sees the club catalog')

    for table in ('library_items', 'library_marks', 'library_loans'):
        check('anonymous cannot read ' + table, 'select * from public.' + table + ';', role='anon', email='alice@example.com', expected_error='42501')
        count('select count(*) from public.' + table + ';', 0, **outsider)
    passed.append('authenticated outsider sees no library data')
    check('outsider cannot add item', "insert into public.library_items(kind,title,added_by) values ('book','Нет доступа','outsider@example.com');", expected_error='42501', **outsider)
    check('member cannot forge item author', "insert into public.library_items(kind,title,added_by) values ('book','Подмена','bella@example.com');", expected_error='42501', **alice)
    check('member cannot rewrite another item', "update public.library_items set title='Подмена' where id='" + book + "';", expected_error='42501', **bella)
    check('creator cannot bypass catalog immutability', "delete from public.library_items where id='" + book + "';", expected_error='42501', **alice)

    invalid_items = [
        ('unknown category', "kind,title,added_by", "'music','Песня','alice@example.com'"),
        ('blank title', "kind,title,added_by", "'book','   ','alice@example.com'"),
        ('untrimmed title', "kind,title,added_by", "'book',' Книга ','alice@example.com'"),
        ('oversized title', "kind,title,added_by", "'book',repeat('я',121),'alice@example.com'"),
        ('oversized creator', "kind,title,added_by,creator", "'book','Книга','alice@example.com',repeat('я',121)"),
        ('oversized description', "kind,title,added_by,blurb", "'book','Книга','alice@example.com',repeat('я',601)"),
        ('oversized genre', "kind,title,added_by,genre", "'book','Книга','alice@example.com',repeat('я',41)"),
        ('zero duration', "kind,title,added_by,duration_minutes", "'book','Книга','alice@example.com',0"),
        ('oversized duration', "kind,title,added_by,duration_minutes", "'game','Игра','alice@example.com',10001"),
        ('zero players', "kind,title,added_by,players_min", "'game','Игра','alice@example.com',0"),
        ('oversized player count', "kind,title,added_by,players_max", "'game','Игра','alice@example.com',31"),
        ('reversed player range', "kind,title,added_by,players_min,players_max", "'game','Игра','alice@example.com',5,2"),
        ('shareable movie', "kind,title,added_by,shareable", "'movie','Фильм','alice@example.com',true"),
    ]
    for label, columns, values in invalid_items:
        check(label + ' rejected', 'insert into public.library_items(' + columns + ') values (' + values + ');', expected_error='23514', **alice)
    count('select count(*) from public.library_items;', 3)
    passed.append('invalid additions leave no catalog rows')

    check('member can rate and mark a book wanted', "insert into public.library_marks(item_id,email,status,rating,review) values ('" + book + "','bella@example.com','want',5,'Обсудим без спойлеров');", **bella)
    check('status can be saved without a rating', "insert into public.library_marks(item_id,email,status) values ('" + game + "','bella@example.com','doing');", **bella)
    check('own rating can be upserted', "insert into public.library_marks(item_id,email,status,rating,review) values ('" + book + "','bella@example.com','done',4,'Прочитала') on conflict(item_id,email) do update set status=excluded.status,rating=excluded.rating,review=excluded.review;", **bella)
    assert sql("select rating||':'||status||':'||review from public.library_marks where item_id='" + book + "';", **alice) == '4:done:Прочитала'
    passed.append('friends see one updated rating and review rather than duplicate votes')
    check('member cannot forge another rating', "insert into public.library_marks(item_id,email,rating) values ('" + film + "','bella@example.com',1);", expected_error='42501', **alice)
    check('outsider cannot rate', "insert into public.library_marks(item_id,email,rating) values ('" + film + "','outsider@example.com',1);", expected_error='42501', **outsider)
    check('changing someone else rating affects no rows', "update public.library_marks set rating=1 where item_id='" + book + "';", **alice)
    assert sql("select rating from public.library_marks where item_id='" + book + "';", **alice) == '4'
    passed.append('foreign rating remains unchanged')
    check('deleting someone else rating affects no rows', "delete from public.library_marks where item_id='" + book + "';", **alice)
    count("select count(*) from public.library_marks where item_id='" + book + "';", 1)
    passed.append('foreign rating remains after unauthorized delete')
    check('rating ownership cannot be transferred', "update public.library_marks set email='alice@example.com' where item_id='" + book + "';", expected_error='42501', **bella)
    for label, assignment in [('zero stars', 'rating=0'), ('six stars', 'rating=6'), ('unknown status', "status='later'"), ('long review', "review=repeat('я',601)")]:
        check(label + ' rejected', "update public.library_marks set " + assignment + " where item_id='" + book + "';", expected_error='23514', **bella)
    check('a rating can be cleared independently of status', "update public.library_marks set rating=null where item_id='" + book + "';", **bella)
    assert sql("select status||':'||(rating is null)::text from public.library_marks where item_id='" + book + "';", **bella) == 'done:true'
    passed.append('clearing rating preserves done status')
    check('timestamp cannot be forged on rating update', "update public.library_marks set updated_at='2000-01-01' where item_id='" + book + "';", **bella)
    count("select count(*) from public.library_marks where item_id='" + book + "' and updated_at > now() - interval '1 minute';", 1)
    passed.append('rating timestamp is refreshed by database')

    borrow_book = "select public.borrow_library_item('" + book + "','borrow');"
    return_book = "select public.borrow_library_item('" + book + "','return');"
    check('anonymous cannot execute loan RPC', borrow_book, role='anon', email='alice@example.com', expected_error='42501')
    check('outsider cannot execute loan RPC', borrow_book, expected_error='42501', **outsider)
    check('missing identity cannot borrow', borrow_book, role='authenticated', email='', expected_error='42501')
    for action in ('null', "'steal'"):
        check('invalid loan action ' + action + ' rejected', "select public.borrow_library_item('" + book + "'," + action + ");", expected_error='22023', **bella)
    check('missing item rejected', "select public.borrow_library_item(null,'borrow');", expected_error='22023', **bella)
    check('nonexistent item rejected', "select public.borrow_library_item('00000000-0000-4000-8000-000000000000','borrow');", expected_error='22023', **bella)
    check('film cannot be borrowed', "select public.borrow_library_item('" + film + "','borrow');", expected_error='55000', **bella)
    check('member cannot insert a loan directly', "insert into public.library_loans(item_id,borrower_email) values ('" + book + "','bella@example.com');", expected_error='42501', **bella)
    check('member can borrow an available copy', borrow_book, **bella)
    assert sql("select borrower_email from public.library_loans where item_id='" + book + "';", **alice) == 'bella@example.com'
    passed.append('friends see actual holder of borrowed copy')
    for table in ('library_marks', 'library_loans'):
        count('select count(*) from public.' + table + ';', 0, **outsider)
    passed.append('outsider cannot read populated reviews or loan identities')
    check('second member cannot take occupied copy', borrow_book, expected_error='55000', **cara)
    check('unrelated member cannot return another loan', return_book, expected_error='42501', **cara)
    check('direct borrower rewrite denied', "update public.library_loans set borrower_email='cara@example.com';", expected_error='42501', **bella)
    check('direct loan delete denied', 'delete from public.library_loans;', expected_error='42501', **bella)
    check('borrower can return copy', return_book, **bella)
    count('select count(*) from public.library_loans;', 0)
    passed.append('return makes copy available')
    check('returning an already available copy is rejected', return_book, expected_error='55000', **bella)
    check('uppercase JWT resolves canonical member email', borrow_book, role='authenticated', email='BELLA@EXAMPLE.COM')
    assert sql('select borrower_email from public.library_loans;') == 'bella@example.com'
    passed.append('loan identity is canonical member email')
    check('copy owner can confirm a return', return_book, **alice)

    # Both clients race for the same initially available copy. Exactly one wins;
    # the other must observe occupied state after the row lock is released.
    def attempt_borrow(identity):
        try:
            sql("select public.borrow_library_item('" + game + "','borrow');", **identity)
            return 'success'
        except AssertionError as error:
            assert '55000' in str(error), error
            return 'occupied'

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt_borrow, [bella, cara]))
    assert sorted(results) == ['occupied', 'success'], results
    count("select count(*) from public.library_loans where item_id='" + game + "';", 1)
    passed.append('concurrent borrow requests produce exactly one borrower')

    check('owner ratings can be removed', "delete from public.library_marks where item_id='" + game + "';", **bella)
    count("select count(*) from public.library_marks where item_id='" + game + "';", 0)
    passed.append('own rating delete is effective')
    sql("insert into public.library_items(kind,title,added_by) values ('book','Оставшаяся рекомендация','departed@example.com');")
    sql("insert into public.library_marks(item_id,email,rating) values ('" + film + "','departed@example.com',5);")
    sql("delete from public.members where email='departed@example.com';")
    count("select count(*) from public.library_items where added_by='departed@example.com';", 1, **alice)
    count("select count(*) from public.library_marks where email='departed@example.com';", 0)
    count('select count(*) from public.library_items;', 0, role='authenticated', email='departed@example.com')
    check('offboarded creator cannot borrow', borrow_book, role='authenticated', email='departed@example.com', expected_error='42501')
    passed.append('offboarding removes marks and access while preserving catalog history')

    assert sql("select has_function_privilege('anon','public.borrow_library_item(uuid,text)','execute');") == 'f'
    assert sql("select has_function_privilege('authenticated','public.borrow_library_item(uuid,text)','execute');") == 't'
    assert sql("select proconfig::text from pg_proc where oid='public.borrow_library_item(uuid,text)'::regprocedure;") == '{"search_path=\\"\\""}'
    passed.append('loan RPC execute grants and empty search_path remain hardened')
    before = sql('select count(*) from public.library_items;')
    check('populated schema remains rerunnable', schema)
    assert sql('select count(*) from public.library_items;') == before
    count('select count(*) from public.library_loans;', 1)
    passed.append('rerun preserves catalog, marks and outstanding loans')

    # Recreate exactly the CHECK layout emitted by the previous three-category
    # DDL, while keeping real populated catalog/mark/loan rows. Its unnamed
    # shareability CHECK was library_items_check; the player range was check1.
    snapshots = {
        table: sql("select coalesce(jsonb_agg(to_jsonb(row) order by to_jsonb(row)::text),'[]'::jsonb)::text from public." + table + ' as row;')
        for table in ('library_items', 'library_marks', 'library_loans')
    }
    sql('''alter table public.library_items
      drop constraint library_items_kind_check,
      drop constraint library_items_shareable_check,
      drop constraint library_items_check,
      add constraint library_items_kind_check check (kind in ('book','movie','game')),
      add constraint library_items_check check (not shareable or kind <> 'movie'),
      add constraint library_items_check1 check (
        players_min is null or players_max is null or players_max >= players_min);''')
    check('previous three-category constraint rejects series before migration',
          "insert into public.library_items(kind,title,added_by) values ('series','Разделение','alice@example.com');",
          expected_error='23514', **alice)
    check('schema upgrades populated previous three-category table', schema)
    for table, snapshot in snapshots.items():
        assert sql("select coalesce(jsonb_agg(to_jsonb(row) order by to_jsonb(row)::text),'[]'::jsonb)::text from public." + table + ' as row;') == snapshot, table
    passed.append('upgrade preserves all previous items, ratings and outstanding loans byte for byte')
    count("select count(*) from pg_constraint where conrelid='public.library_items'::regclass and conname in ('library_items_kind_check','library_items_shareable_check');", 2)
    count("select count(*) from pg_constraint where conrelid='public.library_items'::regclass and conname='library_items_check';", 0)
    passed.append('legacy shareability constraint is replaced with explicitly named constraints')
    check('upgraded table still rejects reversed game player range',
          "insert into public.library_items(kind,title,added_by,players_min,players_max) values ('game','Неверная игра','alice@example.com',5,2);",
          expected_error='23514', **alice)
    series = check('member can add a distinct series after upgrade',
                   "insert into public.library_items(kind,title,creator,added_by,duration_minutes) values ('series','Разделение','Дэн Эриксон','alice@example.com',45) returning id;", **alice)
    assert re.fullmatch(r'[0-9a-f-]{36}', series), series
    count("select count(*) from public.library_items where kind='series';", 1, **bella)
    passed.append('club members can read the new series category')
    check('series cannot be marked as a shared physical copy',
          "insert into public.library_items(kind,title,added_by,shareable) values ('series','Чужая полка','alice@example.com',true);",
          expected_error='23514', **alice)
    check('series rating and watching status can be upserted',
          "insert into public.library_marks(item_id,email,status,rating,review) values ('" + series + "','bella@example.com','doing',5,'Смотрю без спойлеров') on conflict(item_id,email) do update set status=excluded.status,rating=excluded.rating,review=excluded.review;", **bella)
    assert sql("select status||':'||rating::text from public.library_marks where item_id='" + series + "';", **alice) == 'doing:5'
    passed.append('series uses the same personal ratings and shared reviews')
    check('member cannot forge another series rating',
          "insert into public.library_marks(item_id,email,rating) values ('" + series + "','cara@example.com',1);",
          expected_error='42501', **alice)
    check('series cannot be borrowed through RPC',
          "select public.borrow_library_item('" + series + "','borrow');", expected_error='55000', **bella)
    count("select count(*) from public.library_items where kind='series';", 0, **outsider)
    count("select count(*) from public.library_marks where item_id='" + series + "';", 0, **outsider)
    passed.append('series and their ratings remain private to members')
    # RPC checks category itself even if privileged legacy/import code bypassed
    # the table constraint. Restore valid data before rerunning the migration.
    sql("alter table public.library_items drop constraint library_items_shareable_check; update public.library_items set shareable=true where id='" + series + "';")
    check('loan RPC independently rejects series even with corrupt shareable flag',
          "select public.borrow_library_item('" + series + "','borrow');", expected_error='55000', **bella)
    sql("update public.library_items set shareable=false where id='" + series + "';")
    check('four-category schema with populated series remains rerunnable', schema)
    count("select count(*) from public.library_items where kind='series';", 1)
    count("select count(*) from public.library_marks where item_id='" + series + "' and rating=5 and status='doing';", 1)
    count('select count(*) from public.library_loans;', 1)
    passed.append('rerun preserves series, their rating and pre-existing physical loan')
    return {'passed': len(passed), 'checks': passed, 'postgres': sql('select version();')}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run without -O so assertions remain enabled')
    docker, docker_env = local_docker()
    with postgres_container(docker, docker_env) as psql:
        result = run_checks(psql, docker_env)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json_out:
        args.json_out.write_text(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
