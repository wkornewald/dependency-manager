#!/usr/bin/env python
from dependencymanager.core import (clone_cmd, build_cmd, fetch_cmd, push_cmd,
    pull_cmd, status_cmd, diff_cmd, incoming_cmd, outgoing_cmd, deploy_cmd,
    revspec_cmd, tag_cmd, tags_cmd, update_cmd, addremove_cmd, record_cmd,
    commit_cmd, heads_cmd, branch_cmd, merge_cmd, publish_cmd, revert_cmd)
from dependencymanager.repo import get_local_repo
from subprocess import call
import argparse
import os
import sys

DESCRIPTION = """
dm (short for: dependency manager) allows to work with projects that consist of
multiple repositories.
"""

EPILOG = """
type "dm help <command>" for command-specific help
"""

def update_dependency_manager():
    print('Checking for updates to dependency manager...')
    root = os.path.dirname(__file__)
    repo = get_local_repo(root)
    print(repo.pull())

def help_cmd(args):
    if args.command:
        args.subparsers.choices[args.command].print_help()
    else:
        args.parser.print_help()

def main():
    if sys.argv[1:2] == ['all']:
        update_dependency_manager()
        run = [sys.executable, sys.argv[0], '--no-update-check'] + sys.argv[2:]
        for name in os.listdir(os.getcwdu()):
            path = os.path.join(os.getcwdu(), name)
            if os.path.exists(os.path.join(path, '.deps')):
                print('Checking %s:' % name)
                call(run, cwd=path)
                print('\n')
        return

    parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG,
                                     usage='dm [options]')
    parser.add_argument('--no-update-check', action='store_true',
                        help="don't check for updates on pull/fetch/clone")

    repo_parser = argparse.ArgumentParser(add_help=False)
    repo_parser.add_argument('repo', nargs='*',
                             help='limits command to the specified repositories')

    required_repo_parser = argparse.ArgumentParser(add_help=False)
    required_repo_parser.add_argument('repo', nargs='+',
                                      help='limits command to the specified repositories')

    subparsers = parser.add_subparsers(title='commands')

    help = 'make a copy of an existing project'
    subparser = subparsers.add_parser('clone', add_help=False,
                                      help=help, description=help)
    subparser.add_argument('--latest-of',
                           help='picks the latest revision of the given revisions')
    subparser.add_argument('-d', dest='date', help='date to swich to')
    subparser.add_argument('source', help='the URL of the source repository')
    subparser.add_argument('destination', nargs='?', help='the destination directory')
    subparser.set_defaults(func=clone_cmd)

    help = 'rebuild the project after a .dmrc was changed'
    subparser = subparsers.add_parser('build', add_help=False,
                                      help=help, description=help)
    subparser.set_defaults(func=build_cmd)

    for name in ('pu', 'pull'):
        help = 'pull latest incoming changes'
        subparser = subparsers.add_parser(name, add_help=False,
                                          help=help, description=help)
        subparser.set_defaults(func=pull_cmd)

    for name in ('fe', 'fetch'):
        help = 'pull and merge latest incoming changes'
        subparser = subparsers.add_parser(name, add_help=False,
                                          help=help, description=help)
        subparser.set_defaults(func=fetch_cmd)

    for name in ('st', 'status'):
        help = 'list changed files'
        subparser = subparsers.add_parser(name, add_help=False, parents=[repo_parser],
                                          help=help, description=help)
        subparser.set_defaults(func=status_cmd)

    help = 'show a diff of uncommitted changes'
    subparser = subparsers.add_parser('diff', add_help=False, parents=[repo_parser],
                                      help=help, description=help)
    subparser.set_defaults(func=diff_cmd)

    help = 'show incoming changes which would be pulled'
    subparser = subparsers.add_parser('in', add_help=False, parents=[repo_parser],
                                      help=help, description=help)
    subparser.set_defaults(func=incoming_cmd)

    help = 'show changes which would be pushed'
    subparser = subparsers.add_parser('out', add_help=False, parents=[repo_parser],
                                      help=help, description=help)
    subparser.set_defaults(func=outgoing_cmd)

    for name in ('addr', 'addremove'):
        help = 'add all new files, delete all missing files'
        subparser = subparsers.add_parser(name, add_help=False, parents=[repo_parser],
                                          help=help, description=help)
        subparser.set_defaults(func=addremove_cmd)

    for name in ('rec', 'record'):
        help = 'interactively select changes to commit'
        subparser = subparsers.add_parser(name, add_help=False, parents=[repo_parser],
                                          help=help, description=help)
        subparser.set_defaults(func=record_cmd)

    for name in ('ci', 'commit'):
        help = 'commit all outstanding changes'
        subparser = subparsers.add_parser(name, add_help=False, parents=[repo_parser],
                                          help=help, description=help)
        subparser.add_argument('-m', dest='message',
                               help='commit message (same for all repos)')
        subparser.set_defaults(func=commit_cmd)

    for name in ('push', 'pus'):
        help = 'push changes to the server'
        subparser = subparsers.add_parser(name, add_help=False, help=help,
                                          description=help)
        subparser.add_argument('--committed', action='store_true',
                               help='push only committed changes')
        subparser.add_argument('--nodeploy', action='store_true',
                               help="don't deploy after push")
        subparser.set_defaults(func=push_cmd)

    for name in ('reva', 'revert'):
        help = 'revert uncommitted files'
        subparser = subparsers.add_parser(name, add_help=False,
                                          parents=[required_repo_parser],
                                          help=help, description=help)
        subparser.set_defaults(func=revert_cmd)

    help = 'show repository heads'
    subparser = subparsers.add_parser('heads', add_help=False, parents=[repo_parser],
                                      help=help, description=help)
    subparser.set_defaults(func=heads_cmd)

    help = 'deploy pushed changes to production'
    subparser = subparsers.add_parser('deploy', add_help=False,
                                      help=help, description=help)
    subparser.add_argument('--committed', action='store_true',
                           help='deploy only committed changes')
    subparser.set_defaults(func=deploy_cmd)

    help = 'show combined revision number of all repos'
    subparser = subparsers.add_parser('revspec', add_help=False,
                                      help=help, description=help)
    subparser.add_argument('--committed', action='store_true',
                           help='generate revspec even if there are uncommitted changes')
    subparser.set_defaults(func=revspec_cmd)

    help = 'tag the current revspec'
    subparser = subparsers.add_parser('tag', add_help=False, help=help, description=help)
    subparser.add_argument('--committed', action='store_true',
                           help='tag even if there are uncommitted changes')
    subparser.add_argument('--replace', action='store_true',
                           help='overwrite existing tag if it exists')
    subparser.add_argument('name', help='name of the tag')
    subparser.set_defaults(func=tag_cmd)

    help = 'list tags'
    subparser = subparsers.add_parser('tags', add_help=False, help=help, description=help)
    subparser.set_defaults(func=tags_cmd)

    help = 'create/delete branch, list branches'
    subparser = subparsers.add_parser('branch', add_help=False,
                                      help=help, description=help)
    subparser.add_argument('-d', dest='delete', action='store_true', help="delete branch")
    subparser.add_argument('name', nargs='?',
                           help="branch name (leave out to list branches)")
    subparser.set_defaults(func=branch_cmd)

    help = 'merge branches'
    subparser = subparsers.add_parser('merge', add_help=False,
                                      help=help, description=help)
    subparser.add_argument('branch', help="branch name")
    subparser.set_defaults(func=merge_cmd)

    help = 'publish branch by merging into master'
    subparser = subparsers.add_parser('publish', add_help=False, parents=[repo_parser],
                                      help=help, description=help)
    subparser.set_defaults(func=publish_cmd)

    for name in ('up', 'update'):
        help = 'switch to the given revspec or date or branch'
        subparser = subparsers.add_parser(name, add_help=False,
                                          help=help, description=help)
        subparser.add_argument('-d', dest='date', help='date to swich to')
        subparser.add_argument('-C', dest='clean', help='date to swich to')
        subparser.add_argument('revision', help='revspec to swich to', nargs='?')
        subparser.set_defaults(func=update_cmd)

    help = 'show general and command-specific help'
    subparser = subparsers.add_parser('help', add_help=False, help=help, description=help)
    subparser.add_argument('command', choices=set(subparsers.choices), nargs='?',
                           help='optional name of the command')
    subparser.set_defaults(parser=parser, subparsers=subparsers, func=help_cmd)

    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()
    if not args.no_update_check and args.func in (clone_cmd, pull_cmd, fetch_cmd):
        update_dependency_manager()
        run = [sys.executable, sys.argv[0], '--no-update-check'] + sys.argv[1:]
        call(run)
        return
    args.func(args)

if __name__ == '__main__':
    main()
