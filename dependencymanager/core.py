from .repo import get_local_repo, get_remote_repo, ProcessError, DEFAULT_BRANCH
from .utils import AsyncResult, with_lock, get_secure_random_string
from ConfigParser import RawConfigParser
from datetime import datetime
from subprocess import call
from threading import Semaphore
from urllib2 import urlopen
import json
import os
import platform
import sys

# TODO: replace sys.exit() with exceptions

def batch_create_links(root, links):
    if not links:
        return
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          'utilscripts', 'batch-create-links.py')
    params = []
    for link_name, target in links.items():
        path = os.path.join(root, link_name)
        get_or_mkdir(os.path.dirname(path))
        params.append(path)
        params.append(target)
    call([sys.executable, script] + params)

def remove_link(path):
    if os.path.isdir(path) and os.path.islink(path) and platform.system() == 'Windows':
        os.rmdir(path)
    else:
        os.remove(path)

def get_mapped_branches(project):
    return mapped_branches(*project.branches())

def mapped_branches(active_branch, branches):
    if active_branch is None:
        pass
    elif active_branch == DEFAULT_BRANCH:
        active_branch = 'master'
    elif '___' in active_branch:
        active_branch = active_branch.split('___')[0]
    mapped = {'master': DEFAULT_BRANCH}
    for name in branches:
        if '___' in name:
            real_name, internal_name = name.split('___')
            mapped[real_name] = internal_name
    return active_branch, mapped

def get_project_root(start=os.getcwdu()):
    root = None
    next = start
    while True:
        if get_local_repo(next) is not None:
            root = next
        if next == os.path.dirname(next):
            break
        next = os.path.dirname(next)
    if root is None:
        raise ValueError('No repository found at this location!')
    return root

def _normalize_link(repo_name, target):
    if target.startswith('./') or target == '.':
        return repo_name + target[1:]
    return target

def load_repo_config(root):
    config = RawConfigParser()
    config.read(os.path.join(root, '.deps'))
    repo_name = os.path.basename(root)
    package_name = repo_name.rsplit('-', 1)[-1]
    repos = config.items('repos') if config.has_section('repos') else ()

    links = {name.replace('@', package_name):
                _normalize_link(repo_name, target).replace('@', package_name)
             for name, target in (config.items('links')
                                  if config.has_section('links') else ())}

    dependencies = []
    if config.has_option('general', 'dependencies'):
        dependencies = config.get('general', 'dependencies').split()
    repos = dict(repos)
    for name, path in repos.items():
        if not '://' in path and not path.startswith('['):
            repos[name] = os.path.abspath(path)
    return {'repos': repos, 'links': links, 'dependencies': dependencies}

def get_or_mkdir(path):
    if path and not os.path.exists(path):
        os.makedirs(path)
    return path

def get_backups_root(root):
    path = os.path.join(root, 'repos-backups-please-integrate-any-missing-'
                              'changes-and-delete-this-folder')
    get_or_mkdir(path)
    return path

def get_dependencies_root(root):
    return os.path.join(root, '.repos')

def collect_links(base_root):
    for root, dirs, files in os.walk(base_root, followlinks=True):
        for name in dirs[:]:
            path = os.path.join(root, name)
            if os.path.islink(path):
                yield path[len(base_root) + 1:].replace('\\', '/')
                continue
            if name in ('.hg', '.git', '.svn', '.repos'):
                dirs.remove(name)
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                yield path[len(base_root) + 1:].replace('\\', '/')

def get_loaded_dependencies(root):
    deps_root = get_dependencies_root(root)
    dependencies = {}
    dependencies['repos'] = repos = {}
    if os.path.exists(deps_root):
        for name in os.listdir(deps_root):
            # Ignore .DS_Store and other hidden files
            if name.startswith('.'):
                continue
            path = os.path.join(deps_root, name)
            repo = get_local_repo(path)
            if repo is None:
                raise ValueError('No repo "%s" found at path %s' % (name, path))
            repos[name] = repo.get_source()

    dependencies['links'] = links = {}
    deps_base = os.path.abspath(os.path.basename(deps_root)).replace('\\', '/') + '/'
    for name in collect_links(root):
        path = os.path.join(root, name)
        path = os.path.abspath(os.path.join(os.path.dirname(path), os.readlink(path)))
        path = path.replace('\\', '/')
        if not path.startswith(deps_base) or len(path) <= len(deps_base):
            continue
        links[name] = path[len(deps_base):]
    return dependencies

def clone_repo(root, source, destination, revision=None, date=None, branch=None):
    destination = os.path.abspath(destination)
    get_or_mkdir(os.path.dirname(destination))
    if root and try_restore_from_backups(root, os.path.basename(destination), source):
        local_repo = get_local_repo(destination)
        output = 'Restored from backup\n' + local_repo.pull()
    else:
        output = get_remote_repo(source).clone(destination)
    local_repo = get_local_repo(destination)
    if date:
        assert not revision
        assert not branch
    if branch:
        active_branch, branches = local_repo.branches()
        if active_branch != branch:
            if branch in branches:
                output += local_repo.update(branch)
                if revision and revision != branch:
                    output += local_repo.merge(revision)
            else:
                if revision and active_branch != revision:
                    if revision in branches:
                        output += local_repo.update(revision)
                    elif active_branch != DEFAULT_BRANCH:
                        output += local_repo.update(DEFAULT_BRANCH)
                output += local_repo.create_branch(branch)
        elif revision and revision != branch:
            output += local_repo.merge(revision)
    else:
        output += local_repo.update(revision=revision, date=date)
    return 'Cloning %s\n%s' % (source, output)

def collect_repos(root=None):
    if root is None:
        root = get_project_root()
    deps_root = get_dependencies_root(root)
    loaded_repos = get_loaded_dependencies(root)['repos']
    repos = {}
    repos['.'] = get_local_repo(root)
    for name in loaded_repos:
        path = os.path.join(deps_root, name)
        repos[name] = get_local_repo(path)
    return repos

def get_humane_repo_name(repos, name):
    if name in repos:
        return name

    matches = set()
    for repo_name in repos:
        parts = {part for subpart in repo_name.split('-') for part in subpart.split('_')}
        for part in parts:
            if part.startswith(name):
                matches.add(repo_name)

    if len(matches) == 1:
        return matches.pop()
    elif len(matches) > 1:
        raise ValueError('Multiple repos matched "%s": %s' % (name, ', '.join(matches)))
    raise ValueError('Couldn\'t find any repo matching the name "%s"' % name)

def filter_repos_by_name(repos, repo_names):
    names = {get_humane_repo_name(repos, name) for name in repo_names}
    return {name: repos[name] for name in names}

def run_in_all_repos(action, parallel=True, max_parallel=None, repo_names=None,
                     kwargs=None, project_kwargs=None, skip_project=False):
    if kwargs is None:
        kwargs = {}
    if project_kwargs is None:
        project_kwargs = {}
    project_kwargs = dict(kwargs, **project_kwargs)

    repos = collect_repos()
    if repo_names is not None:
        repos = filter_repos_by_name(repos, repo_names)

    if skip_project:
        repos.pop('.', None)
    # Rename the project repo name to something more human-readable
    if '.' in repos:
        repos['<project>'] = repos.pop('.')

    if not parallel:
        for name in sorted(repos):
            print('%s: %s' % (action.replace('_', ' ').capitalize(), name))
            kw = project_kwargs if name == '<project>' else kwargs
            getattr(repos[name], action)(**kw)
        return

    threads = {}
    if max_parallel >= 1:
        lock = Semaphore(max_parallel)
    for name in repos:
        func = getattr(repos[name], action)
        if max_parallel >= 1:
            func = with_lock(func, lock)
        kw = project_kwargs if name == '<project>' else kwargs
        threads[name] = AsyncResult(func, kwargs=kw)

    errors = []
    for name in sorted(threads):
        result = threads[name].do()
        if isinstance(result, ProcessError):
            errors.append(name)
        if result and (not isinstance(result, basestring) or result.strip()):
            print('%s: %s' % (action.replace('_', ' ').capitalize(), name))
            print(result)

    if errors:
        sys.stderr.write('\n'
                         'Errors happened for the following repos: %s\n'
                         'Scroll upwards to see the errors. ;)\n'
                         % ', '.join(errors))
        sys.exit(1)

def fetch_repo(name, root):
    if name is None:
        name = '<project>'
    repo = get_local_repo(root)
    result = repo.fetch()
    if result and result.strip():
        return 'Fetching %s\n%s' % (name, result)
    return ''

def pull_repo(name, root):
    if name is None:
        name = '<project>'
    repo = get_local_repo(root)
    result = repo.pull()
    if result and result.strip():
        return 'Pulling %s\n%s' % (name, result)
    return ''

def update_repo(name, root, revision=None, date=None):
    if name is None:
        name = '<project>'
    repo = get_local_repo(root)
    result = repo.update(revision=revision, date=date)
    if result and result.strip():
        return 'Updating %s\n%s' % (name, result)
    return ''

def merge_repo(name, root, revision=None):
    if name is None:
        name = '<project>'
    repo = get_local_repo(root)
    result = repo.merge(branch=revision)
    if result and result.strip():
        return 'Merging %s\n%s' % (name, result)
    return ''

def send_deploy_signal(deploy_url, repo_url, revisions):
    data = json.dumps([repo_url, revisions])
    urlopen(deploy_url, data)

def move_to_backups(root, name):
    deps_root = get_dependencies_root(root)
    backups_root = get_backups_root(root)
    backup_dir = os.path.join(backups_root, name,
        datetime.utcnow().isoformat().replace(':', '-'))

    try:
        os.renames(os.path.join(deps_root, name), backup_dir)
    except:
        sys.stderr.write('Error: Could not move %s. Please close '
                         'any open files in that repository.\n'
                         % name)
        sys.exit(1)

    return backup_dir

def try_restore_from_backups(root, name, source=None):
    deps_root = get_dependencies_root(root)
    backups_root = os.path.join(get_backups_root(root), name)
    if os.path.exists(backups_root):
        backups = sorted(os.listdir(backups_root), reverse=True)
        for backup in backups:
            backup_dir = os.path.join(backups_root, backup)
            repo = get_local_repo(backup_dir)
            if not repo or (source and repo.get_source() != source):
                continue
            try:
                os.renames(backup_dir, os.path.join(deps_root, name))
            except:
                sys.stderr.write('Error: Could not move %s. Please close '
                                 'any open files in that repository.\n'
                                 % name)
                sys.exit(1)
            return True
    return False

def build_project(root, preload=None, revision=None, active_branch=None, branches=None,
                  **kwargs):
    has_revision = revision is not None
    if not has_revision:
        revision = {}

    if branches is None:
        branches = get_mapped_branches(get_local_repo(root))[1]

    if preload is not None:
        kw = kwargs.copy()
        if has_revision:
            if isinstance(revision, dict):
                rev = revision.get('.')
            else:
                rev = (branches[revision] if revision == 'master'
                       else '%s___%s' % (revision, branches[revision]))
            kw['revision'] = rev
        print(preload(None, root, **kw))

    # Set active branch after preload call because preload might switch branches
    if active_branch is None:
        active_branch = get_mapped_branches(get_local_repo(root))[0]

    deps_root = get_dependencies_root(root)
    loaded_dependencies = get_loaded_dependencies(root)
    loaded_repos = loaded_dependencies['repos']
    existing_links = loaded_dependencies['links']
    unprocessed_repos = set(loaded_repos.keys())
    unprocessed_links = set(existing_links.keys())
    config = load_repo_config(root)

    warnings = []
    try:
        to_load = sorted(config['repos'].items(), key=lambda x: x[0])
        to_link = list(config['links'].items())
        post_load = []
        if to_load:
            get_or_mkdir(deps_root)
        while to_load:
            name, source = to_load.pop()
            destination = os.path.normpath(os.path.join(deps_root, name))
            rev = None
            if has_revision:
                rev = (revision.get(name) if isinstance(revision, dict)
                       else branches[revision])
            if name not in loaded_repos or source != loaded_repos[name]:
                if name in loaded_repos:
                    backup_dir = move_to_backups(root, name)
                    warnings.append('\nWarning: The source location of %s has '
                                    'changed. Your existing repository has been '
                                    'moved to\n%s\n' % (name, backup_dir))
                kw = kwargs
                if not has_revision or not isinstance(revision, dict):
                    kw = dict(kwargs, branch=branches[active_branch])
                thread = AsyncResult(clone_repo, (root, source, destination, rev), kw)
                post_load.insert(0, (name, source, destination, thread))
            elif preload is not None:
                kw = kwargs.copy()
                if has_revision:
                    kw['revision'] = rev
                thread = AsyncResult(preload, (name, destination), kw)
                post_load.insert(0, (name, source, destination, thread))
            else:
                post_load.insert(0, (name, source, destination, None))

        post_load = list(reversed(post_load))
        while post_load:
            name, source, destination, thread = post_load.pop()
            if thread is not None:
                result = thread.do()
                if isinstance(result, ProcessError):
                    warnings.append('Error while processing %s:\n%s\n'
                                    % (name, str(result)))
                elif result and result.strip():
                    print(result)

            if name in unprocessed_repos:
                unprocessed_repos.remove(name)

            subconfig = load_repo_config(destination)

            # Check config
            if subconfig['repos']:
                sys.stderr.write('Error: The .deps file in %s has its own repo '
                                 'dependencies. This is very inefficient and thus '
                                 'disallowed.\n' % name)
                sys.exit(1)

            for subdependency in subconfig['dependencies']:
                if subdependency not in config['repos']:
                    sys.stderr.write('Error: The .deps file in %s has a dependency to '
                                     '%s which is not listed in the project .deps.\n'
                                     % (name, subdependency))
                    sys.exit(1)

            # Check conflicts in link definitions
            for subname, subtarget in subconfig['links'].items():
                if subtarget != name and not subtarget.startswith(name + '/'):
                    sys.stderr.write('Error: The .deps file in %s defines a '
                                     'link %s pointing to %s which is not part '
                                     'of that repository.\n'
                                     % (name, subname, subtarget))
                    sys.exit(1)
                to_link.append((subname, subtarget))

        for name in unprocessed_repos:
            backup_dir = move_to_backups(root, name)
            warnings.append('\nWarning: The repository %s is not a '
                            'dependency, anymore. Your existing repository '
                            'has been moved to\n%s\n' % (name, backup_dir))

        new_links = {}
        while to_link:
            name, target = to_link.pop()

            if target != existing_links.get(name):
                link_path = os.path.join(root, name)
                if os.path.exists(link_path) and os.path.islink(link_path):
                    remove_link(link_path)
                relative_target = os.path.relpath(os.path.join(root, '.repos', target),
                                                  os.path.dirname(link_path))
                new_links[name] = relative_target

            if name in unprocessed_links:
                unprocessed_links.remove(name)

        for name in unprocessed_links:
            remove_link(os.path.join(root, name))

        # We batch-create multiple links because on Windows symlinks require
        # admin permission and we only want to ask the user for permission once
        batch_create_links(root, new_links)
    finally:
        if warnings:
            sys.stderr.write('\n'.join(warnings))

def load_revisions(root, only_committed=False):
    config = RawConfigParser()
    config.read(os.path.join(root, '.dmrc'))
    if config.has_option('signals', 'deploy'):
        deploy_url = config.get('signals', 'deploy')
    else:
        deploy_url = None

    repos = collect_repos()
    revisions = {}

    repo_url = repos['.'].get_source()
    for name, repo in repos.items():
        revisions[name] = repo.get_revision(no_uncommitted=not only_committed)

    return deploy_url, repo_url, revisions

def push_project(root, committed=False, deploy=True):
    if deploy:
        deploy_url, repo_url, revisions = load_revisions(root, only_committed=committed)

    project = get_local_repo(get_project_root())
    active_branch, branches = get_mapped_branches(project)
    run_in_all_repos('push')

    if deploy and deploy_url:
        send_deploy_signal(deploy_url, repo_url, revisions)

def deploy_project(root, committed=False):
    deploy_url, repo_url, revisions = load_revisions(root, only_committed=committed)
    if deploy_url:
        send_deploy_signal(deploy_url, repo_url, revisions)

def clone_project(source, destination, revision=None, date=None):
    repo = get_remote_repo(source)
    if not destination:
        destination = repo.get_default_destination()
    print(clone_repo(None, source, destination, revision=revision.get('.'), date=date))
    project = get_local_repo(destination)
    active_branch, branches = get_mapped_branches(project)
    if 'stable' in branches and not revision:
        build_project(destination, update_repo, revision='stable', date=date,
                      active_branch=active_branch, branches=branches)
    else:
        build_project(destination, revision=revision, date=date)
        print('\n\n')
        print('-----------------------------------------------------------------')
        print('There is no stable branch in this project. You should create one.')
        print('IMPORTANT: Exactly one developer should create the stable branch.')
        print('-----------------------------------------------------------------')

def get_project_root_ensured():
    root = get_project_root()
    if os.getcwdu() != root:
        sys.stderr.write('Error: This command must be executed from '
                         'the project root folder because it might need to '
                         'reorganize large parts of the directory tree.\n')
        sys.exit(1)
    return root

def parse_revspec(revspec):
    if not revspec:
        return {}
    revision = {}
    for spec in revspec.split(';'):
        name, revs = spec.split(':', 1)
        revision[name] = revs.split(',')
    return revision

def clone_cmd(args):
    revision = parse_revspec(args.latest_of)
    date = args.date or None
    clone_project(args.source, args.destination, revision=revision, date=date)

def build_cmd(args):
    root = get_project_root_ensured()
    build_project(root)

def pull_cmd(args):
    root = get_project_root_ensured()
    build_project(root, pull_repo)

def fetch_cmd(args):
    root = get_project_root_ensured()
    build_project(root, fetch_repo)

def status_cmd(args):
    run_in_all_repos('status', repo_names=args.repo or None)

def diff_cmd(args):
    run_in_all_repos('diff', repo_names=args.repo or None)

def incoming_cmd(args):
    run_in_all_repos('incoming', repo_names=args.repo or None)

def outgoing_cmd(args):
    run_in_all_repos('outgoing', repo_names=args.repo or None)

def addremove_cmd(args):
    run_in_all_repos('addremove', repo_names=args.repo or None)

def record_cmd(args):
    run_in_all_repos('record', repo_names=args.repo or None, parallel=False)

def commit_cmd(args):
    run_in_all_repos('commit', parallel=bool(args.message),
                     repo_names=args.repo or None,
                     kwargs={'message': args.message})

def push_cmd(args):
    root = get_project_root_ensured()
    build_project(root)
    push_project(root, committed=args.committed, deploy=not args.nodeploy)

def heads_cmd(args):
    run_in_all_repos('heads', repo_names=args.repo or None)

def deploy_cmd(args):
    root = get_project_root_ensured()
    build_project(root)
    deploy_project(root, committed=args.committed)

def revspec_cmd(args):
    root = get_project_root()
    build_project(root)

    revisions = load_revisions(root, only_committed=args.committed)[-1]
    revspec = ';'.join('%s:%s' % (name, revision)
                       for name, revision in revisions.items())
    print(revspec)

def parse_tags(path):
    if not os.path.exists(path):
        return {}

    with open(path, 'r') as fp:
        content = fp.read()

    tags = {}
    for line in content.splitlines():
        tag, revspec = line.rsplit(' ', 1)
        tags[tag] = revspec
    return tags

def tag_cmd(args):
    root = get_project_root()
    build_project(root)

    revisions = load_revisions(root, only_committed=args.committed)[-1]
    revspec = ';'.join('%s:%s' % (name, revision)
                       for name, revision in revisions.items())

    tags_path = os.path.join(root, '.dmtags')
    tags = parse_tags(tags_path)
    if args.name in tags and not args.replace:
        sys.stderr.write('The tag %s already exists! Use --replace to overwrite.\n'
                         % args.name)
        sys.exit(1)

    tags[args.name] = revspec

    with open(tags_path, 'w') as fp:
        for tag in sorted(tags):
            fp.write('%s %s\n' % (tag, tags[tag]))

    repo = get_local_repo(root)
    repo.commit('added tag %s' % args.name, tags_path)

def tags_cmd(args):
    root = get_project_root()
    tags_path = os.path.join(root, '.dmtags')
    content = ''
    if os.path.exists(tags_path):
        with open(tags_path, 'r') as fp:
            content = fp.read()

    for line in content.splitlines():
        print(line.rsplit(' ', 1)[0])

def branch_cmd(args):
    root = get_project_root_ensured()
    build_project(root)

    project = get_local_repo(root)
    active_branch, branches = get_mapped_branches(project)

    if not args.name:
        if args.delete:
            sys.stderr.write('Error: Option -d requires a branch name\n')
            return -1
        for branch in sorted(branches):
            print('%s %s' % ('*' if branch == active_branch else ' ', branch))
        return

    if args.delete:
        if args.name not in branches:
            sys.stderr.write("Error: Branch doesn't exist\n")
            return -1
        branch = branches[args.name]
        if branch == DEFAULT_BRANCH:
            sys.stderr.write("Error: Default branch can't be deleted\n")
            return -1
        if args.name == active_branch:
            sys.stderr.write("Error: Active branch can't be deleted. "
                             "Switch to a different branch, first.\n")
            return -1
        run_in_all_repos('delete_branch', kwargs={'name': branch},
                         project_kwargs={'name': '%s___%s' % (args.name, branch)})
        return

    if args.name in branches:
        sys.stderr.write("Error: Branch already exists\n")
        return -1

    branch = 'dm_' + get_secure_random_string(16)
    run_in_all_repos('create_branch', kwargs={'name': branch},
                     project_kwargs={'name': '%s___%s' % (args.name, branch)})

def merge_cmd(args):
    root = get_project_root_ensured()
    build_project(root, merge_repo, revision=args.branch)

def publish_cmd(args):
    root = get_project_root_ensured()
    project = get_local_repo(root)
    active_branch, branches = get_mapped_branches(project)
    run_in_all_repos('merge_into', repo_names=args.repo or None, skip_project=True,
        kwargs={'branch': DEFAULT_BRANCH, 'current_branch': branches[active_branch]})

def update_cmd(args):
    root = get_project_root_ensured()
    tags_path = os.path.join(root, '.dmtags')
    tags = parse_tags(tags_path)
    active_branch = branches = None
    if args.revision and ':' not in args.revision:
        project = get_local_repo(root)
        active_branch, branches = get_mapped_branches(project)
        if args.revision in tags:
            revision = parse_revspec(tags[args.revision])
        elif args.revision in branches:
            revision = args.revision
        else:
            sys.stderr.write('The given revision does not exist.\n')
            sys.exit(1)
    else:
        revision = parse_revspec(args.revision)
    date = args.date or None
    build_project(root, update_repo, revision=revision, date=date,
                  active_branch=active_branch, branches=branches)

def revert_cmd(args):
    run_in_all_repos('revert', repo_names=args.repo)
