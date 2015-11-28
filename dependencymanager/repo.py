from ConfigParser import ConfigParser
from cStringIO import StringIO
from subprocess import Popen, PIPE, STDOUT
import os
import platform
import re
import sys

# TODO: replace sys.exit() with exceptions

DEFAULT_BRANCH = '$default'

hg_rev_re = re.compile(r'changeset:\s*(\d+):.*', re.UNICODE)
hg_bookmark_re = re.compile(r'\s*(\*)?\s*([^\s]+)\s*-?\d+:([^\s]+)', re.UNICODE)
hg_divergent_re = re.compile('divergent bookmark ([^\s]+) stored as .*', re.UNICODE)
git_branch_re = re.compile(r'\s*(\*)?\s*([^\s]+)\s*([^\s]+).*', re.UNICODE)
git_default_branch_re = re.compile(r'\s*origin/HEAD\s*->\s*origin/([^\s]+)', re.UNICODE)

class RemoteRepo(object):
    def __init__(self, source):
        self.source = source

    def get_default_destination(self):
        return self.source.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]

    def clone(self, destination, branch):
        raise NotImplementedError()

class LocalRepo(object):
    def __init__(self, root, path=None):
        # root is the repo root while path is the path from which to execute commands
        # (e.g., a user would diff a file from his current path instead of from root)
        self.root = root
        self.path = path if path is not None else root

    def get_source(self):
        raise NotImplementedError()

    def get_revision(self, no_uncommitted=True):
        raise NotImplementedError()

    def get_branch_name(self, branch):
        if branch == DEFAULT_BRANCH:
            return self.default_branch()
        return branch

    def update_or_create_branch(self, branch, branches=None):
        if branches is None:
            current_branch, branches = self.branches()
            if branch == current_branch:
                return ''
        if branch in branches:
            return self.update(branch)
        else:
            return self.create_branch(branch)

    def merge_into(self, branch, current_branch=None):
        if current_branch is None:
            current_branch = self.branches()[0]
        result = ''
        try:
            result += self.update(branch)
            result += self.merge(current_branch)
        finally:
            result += self.update(current_branch)
        return result

    def default_branch(self):
        raise NotImplementedError()

    def branches(self):
        raise NotImplementedError()

    def create_branch(self, name):
        raise NotImplementedError()

    def delete_branch(self, name):
        raise NotImplementedError()

    def update(self, revision=None, date=None, clean=False):
        raise NotImplementedError()

    def fetch(self):
        raise NotImplementedError()

    def pull(self):
        raise NotImplementedError()

    def merge(self, branch=None):
        raise NotImplementedError()

    def push(self):
        raise NotImplementedError()

    def diff(self):
        raise NotImplementedError()

    def status(self):
        raise NotImplementedError()

    def incoming(self):
        raise NotImplementedError()

    def outgoing(self):
        raise NotImplementedError()

    def commit(self, message='', paths=None):
        raise NotImplementedError()

    def addremove(self):
        raise NotImplementedError()

    def revert(self):
        raise NotImplementedError()

    def record(self):
        raise NotImplementedError()

    def heads(self, divergent_only=True):
        raise NotImplementedError()

class RemoteFakeLocalRepo(RemoteRepo):
    def clone(self, destination):
        return 'Cloning not possible for local repos'

class RemoteHGRepo(RemoteRepo):
    def clone(self, destination):
        return call_hg('clone', self.source, destination, pipe=True)

class LocalHGRepo(LocalRepo):
    def get_source(self):
        config = ConfigParser()
        config.read(os.path.join(self.root, '.hg', 'hgrc'))
        if not config.has_option('paths', 'default'):
            return '[local]'
        return config.get('paths', 'default')

    def get_revision(self, no_uncommitted=True):
        pair = call_hg('id', '-i', '-b', pipe=True, cwd=self.root).strip()
        revision, branch = pair.split(' ', 1)
        if revision.endswith('+') and no_uncommitted:
            raise ValueError('Repository has uncommitted changes: %s' % self.root)
        if branch != 'default':
            revision = call_hg('id', '-r', 'default', '-i', pipe=True, cwd=self.root)
            revision = revision.strip()
        return revision.rstrip('+')

    def _get_real_bookmark_name(self, name):
        if '@' not in name:
            return name, False
        real_name, divergent = name.split('@', 1)
        if not real_name:
            real_name = DEFAULT_BRANCH
        if divergent:
            return real_name, True
        return real_name, False

    def _bookmarks(self):
        branches = {}
        needs_merge = {}
        active_branch = None
        output = call_hg('bookmark', pipe=True, cwd=self.root).rstrip().lstrip('\n')
        if output == 'no bookmarks set':
            return active_branch, branches
        for line in output.split('\n'):
            match = hg_bookmark_re.match(line)
            if not match:
                continue
            active, branch, revision = match.groups()
            name, divergent = self._get_real_bookmark_name(branch)
            if divergent:
                if active:
                    raise ProcessError('Error: divergent bookmark %s is marked active!'
                                       % branch)
                if name in needs_merge:
                    raise ProcessError('Error: multiple divergent bookmarks (%s) found!'
                                       % name)
                needs_merge[name] = (branch, revision)
            if active:
                active_branch = name
            branches[name] = revision
        return active_branch, branches, needs_merge

    def default_branch(self):
        return '@'

    def branches(self):
        return self._bookmarks()[:2]

    def create_branch(self, name):
        name = self.get_branch_name(name)
        return call_hg('bookmark', name, pipe=True, cwd=self.root).strip() or \
               'Created branch {}\n'.format(name)

    def delete_branch(self, name):
        name = self.get_branch_name(name)
        output = call_hg('bookmark', '-d', name, pipe=True, cwd=self.root)
        try:
            output += call_hg('push', '-B', name, pipe=True, cwd=self.root, max_status=1)
        except ProcessError as error:
            if 'does not exist on the local or remote repository!' not in error.message:
                raise
        return output.strip()

    def update(self, revision=None, date=None, clean=False):
        if isinstance(revision, basestring):
            revision = (revision,)
        args = []
        if clean:
            args.append('-C')
        if date:
            args.extend(['-d', '<' + date])
        elif not revision:
            pass
        elif len(revision) == 1:
            args.append(self.get_branch_name(revision[0]))
        else:
            revnumbers = []
            for rev in revision:
                stdout = call_hg('log', '-r', rev, pipe=True, cwd=self.root)
                revnumbers.append(int(hg_rev_re.search(stdout).group(1)))
            latest = revision[revnumbers.index(max(revnumbers))]
            args.append(latest)
        output = call_hg('update', *args, pipe=True, cwd=self.root)
        output = self._merge_if_needed(output)
        return output

    def pull(self, merge=False):
        if self.get_source() == '[local]':
            return 'repository default not found!\n'
        result = call_hg('pull', '--update', pipe=True, cwd=self.root)
        if 'merge branches' in result.lower() or \
                'divergent bookmark' in result.lower():
            if merge:
                result = self._merge_if_needed(result)
            else:
                raise ProcessError(result)
        elif 'no changes found' in result:
            return 'No changes found\n'
        return result

    def fetch(self):
        return self.pull(merge=True)

    def _merge_if_needed(self, output=''):
        active_branch, branches, needs_merge = self._bookmarks()
        if active_branch in needs_merge:
            output += ('Divergent branch found. Merge needed.\n'
                       'Merging automatically...\n')
            output = self.merge(output=output)
        return output

    def merge(self, branch=None, output=''):
        try:
            args = []
            if branch:
                branch = self.get_branch_name(branch)
                args.append(branch)
            output += call_hg('merge', *args, pipe=True, cwd=self.root)
            message = 'Merged branch %s' % branch if branch else 'Merged automatically'
            if 'branch merge' in output:
                output += self.commit(message)
        except ProcessError as error:
            if error.message.strip().endswith('has no effect'):
                return output
            else:
                raise ProcessError('%s\n%s' % (output, error.message))
        return output + 'Finished automatic merge\n'

    def push(self):
        result = call_hg('push', pipe=True, cwd=self.root, max_status=1)
        if result.strip().endswith('no changes found'):
            return ''
        if 'remote has heads on branch' in result or \
                'that are not known locally' in result:
            raise ProcessError('Not all branches could be pushed:\n' + result)
        return result

    def diff(self):
        return call_hg('diff', pipe=True, cwd=self.path)

    def status(self):
        return call_hg('status', pipe=True, cwd=self.path)

    def incoming(self):
        result = call_hg('incoming', pipe=True, cwd=self.root, max_status=1)
        return self._normalize_changesets(result)

    def outgoing(self):
        result = call_hg('outgoing', pipe=True, cwd=self.root, max_status=1)
        return self._normalize_changesets(result)

    def _normalize_changesets(self, result):
        lines = result.rstrip().split('\n')
        if len(lines) < 3:
            # An error occured
            return result
        if len(lines) == 3:
            # Nothing incoming
            return ''
        else:
            # Return changesets
            return '\n'.join(lines[2:]) + '\n'

    def commit(self, message='', paths=None):
        if isinstance(paths, basestring):
            paths = (paths,)
        command = ['commit']
        if message:
            command.extend(['-m', message])
        if paths:
            command.extend(paths)
        result = call_hg(*command, pipe=bool(message), cwd=self.path, max_status=1)
        if message and result.strip().endswith('nothing changed'):
            return ''
        return result

    def addremove(self):
        return call_hg('addremove', '-s60', pipe=True, cwd=self.root)

    def revert(self):
        return call_hg('revert', '--all', '--no-backup', pipe=True, cwd=self.root)

    def record(self):
        return call_hg('record', cwd=self.root)

    def heads(self, divergent_only=True):
        if not divergent_only:
            return call_hg('heads', pipe=True, cwd=self.root)
        needs_merge = self._bookmarks()[2]
        if needs_merge:
            return 'Needs merge: %s' % ', '.join(map(self.get_branch_name, needs_merge))
        return ''

class RemoteGitRepo(RemoteRepo):
    def get_default_destination(self):
        destination = super(RemoteGitRepo, self).get_default_destination()
        if destination.endswith('.git'):
            return destination.rsplit('.', 1)[0]
        return destination

    def clone(self, destination):
        return call_git('clone', self.source, destination, pipe=True)

class LocalGitRepo(LocalRepo):
    def get_source(self):
        data = StringIO()
        path = os.path.join(self.root, '.git', 'config')
        fp = open(path, 'r')
        data.write(fp.read().replace('\n\t', '\n'))
        fp.close()
        data.seek(0)
        config = ConfigParser()
        config.readfp(data)
        source = config.get('remote "origin"', 'url')
        return '[git]' + source

    def get_revision(self, no_uncommitted=True):
        if no_uncommitted:
            status = self.status()
            if status.strip():
                raise ValueError('Repository has uncommitted changes: %s' % self.root)
        return call_git('rev-parse', 'HEAD', pipe=True, cwd=self.root).strip()

    def default_branch(self):
        output = call_git('branch', '-r', pipe=True, cwd=self.root)
        for line in output.strip().split('\n'):
            match = git_default_branch_re.match(line)
            if not match:
                continue
            return match.group(1)
        return 'master'

    def _branches(self):
        branches = {}
        remote_branches = {}
        active_branch = None
        default_branch = self.default_branch()
        output = call_git('branch', '-a', '--no-abbrev', '-v', pipe=True, cwd=self.root)
        for line in output.strip().split('\n'):
            match = git_branch_re.match(line)
            if not match:
                continue
            active, branch, revision = match.groups()
            if branch.endswith('/HEAD') or revision == '->':
                continue
            if branch.startswith('remotes/'):
                branch = branch.split('/', 2)[2]
                if branch == default_branch:
                    branch = DEFAULT_BRANCH
                remote_branches[branch] = revision
            if branch == default_branch:
                branch = DEFAULT_BRANCH
            if active:
                active_branch = branch
            branches[branch] = revision
        return active_branch, branches, remote_branches

    def branches(self):
        active_branch, branches, remote_branches = self._branches()
        for branch, revision in remote_branches.items():
            branches.setdefault(branch, revision)
        return active_branch, branches

    def create_branch(self, name):
        # We have to check if there is a remote branch with this name before creating
        # a local one
        name = self.get_branch_name(name)
        if name in self.branches()[1]:
            raise ProcessError('Error: Branch %s already exists.' % name)
        output = call_git('checkout', '-b', name, pipe=True, cwd=self.root).strip()
        if output.lower().startswith('switched to a new branch'):
            return ''
        return output

    def delete_branch(self, name):
        remote = name in self._branches()[2]
        name = self.get_branch_name(name)
        output = call_git('branch', '-d', name, pipe=True, cwd=self.root)
        if remote:
            output += call_git('push', '--delete', 'origin', name, pipe=True,
                               cwd=self.root)
        output = output.strip()
        if output.lower().startswith('deleted branch '):
            return
        return output

    def update(self, revision=None, date=None, clean=False):
        if isinstance(revision, basestring):
            revision = (revision,)
        output = ''
        if date:
            stdout = call_git('log', '-n', '1', '--before', date, pipe=True,
                              cwd=self.root)
            revision = stdout.split('\n', 1)[0].split(' ', 1)[1]
        elif revision and len(revision) == 1:
            # Before switching branches make sure we know all remote branches
            output += call_git('fetch', pipe=True, cwd=self.root)
            revision = self.get_branch_name(revision[0])
        elif revision:
            stdout = call_git('rev-list', '--branches', pipe=True, cwd=self.root)
            revlist = stdout.strip().split('\n')
            revision = revlist[max(map(revlist.index, revision))]
        else:
            # Checkout active branch
            revision = self.get_branch_name(self.branches()[0])
            if not revision:
                revision = 'master'
        if clean:
            call_git('reset', '--hard', pipe=True, cwd=self.root)
        output += call_git('checkout', revision, pipe=True, cwd=self.root)
        if revision == 'master':
            revision = DEFAULT_BRANCH
        if revision in self._branches()[2]:
            output += self.fetch()
        return output

    def pull(self):
        try:
            result = call_git('pull', pipe=True, cwd=self.root)
        except ProcessError as error:
            if 'There is no tracking information for the current branch' in error.message:
                return ''
            if 'Automatic merge failed' in error.message:
                return error.message
            raise
        if result.strip().endswith('Already up-to-date.'):
            return 'No changes found\n'
        return result

    def fetch(self):
        result = self.pull()
        if not result or 'No changes found' in result:
            return result
        return self.merge(output=result)

    def merge(self, branch=None, output=''):
        try:
            args = []
            if branch:
                branch = self.get_branch_name(branch)
                args.append(branch)
            output += call_git('mergetool', '--no-prompt', *args, pipe=True,
                               cwd=self.root)
            if 'No files need merging' in output:
                return ''
            message = 'Merged branch %s' % branch if branch else 'Merged automatically'
            output += self.commit(message)
        except ProcessError as error:
            raise ProcessError('%s\n%s' % (output, error.message))
        return output + 'Finished automatic merge\n'

    def push(self):
        result = call_git('push', '--all', '-u', pipe=True, cwd=self.root)
        if result.strip().endswith('Everything up-to-date'):
            return ''
        return result

    def diff(self):
        return call_git('diff', pipe=True, cwd=self.path)

    def status(self):
        return call_git('status', '-s', pipe=True, cwd=self.path)

    def incoming(self):
        call_git('fetch', pipe=True, cwd=self.root)
        active, branches, remote = self._branches()
        output = []
        for branch in branches:
            if branch not in remote:
                continue
            branch = self.get_branch_name(branch)
            output.append(call_git('log', '..origin/%s' % branch, pipe=True,
                                   cwd=self.root))
        return '\n\n'.join(output)

    def outgoing(self):
        call_git('fetch', pipe=True, cwd=self.root)
        active, branches, remote = self._branches()
        output = []
        for branch in branches:
            if branch not in remote:
                output.append('New branch %s\n' % self.get_branch_name(branch))
                continue
            branch = self.get_branch_name(branch)
            output.append(call_git('log', 'origin/%s..' % branch, pipe=True,
                                   cwd=self.root))
        return '\n\n'.join(output)

    def addremove(self):
        return call_git('add', '-A', pipe=True, cwd=self.root)

    def revert(self):
        return call_git('reset', '--hard', pipe=True, cwd=self.root)

    def record(self):
        has_changes = bool(call_git('status', '-s', '--untracked-files=no',
                                    pipe=True, cwd=self.path).strip())
        if not has_changes:
            print('no changes to record\n')
            return
        return call_git('commit', '-p', cwd=self.root)

    def commit(self, message='', paths=None):
        has_changes = bool(call_git('status', '-s', '--untracked-files=no',
                                    pipe=True, cwd=self.path).strip())
        if not has_changes:
            return ''
        if isinstance(paths, basestring):
            paths = (paths,)
        command = ['commit']
        if not paths:
            command.append('-a')
        if message:
            command.extend(['-m', message])
        if paths:
            command.extend(paths)
        return call_git(*command, pipe=bool(message), cwd=self.path)

    def heads(self, divergent_only=True):
        # TODO: Git doesn't have a heads command, so let's ignore it for now
        return ''

REMOTE_REPOS = {
    'hg': RemoteHGRepo,
    'git': RemoteGitRepo,
    'local': RemoteFakeLocalRepo,
}

repo_type_re = re.compile(r'^\[(\w+)\](.*)$', re.UNICODE)

def get_remote_repo(source):
    repo_type = 'hg'
    match = repo_type_re.match(source)
    if match:
        repo_type, source = match.groups()
    return REMOTE_REPOS[repo_type](source)

LOCAL_REPOS = {
    '.hg': LocalHGRepo,
    '.git': LocalGitRepo,
}

def find_local_repo(root=os.getcwdu(), path=os.getcwdu()):
    repo_class = detect_local_repo(root)
    if repo_class is not None:
        return repo_class(root, path)
    parent = os.path.dirname(root)
    if parent == root:
        return None
    return find_local_repo(parent, path)

def find_repo_root(root=os.getcwdu()):
    repo = find_local_repo(root)
    if repo is None:
        return None
    return repo.root

def get_local_repo(root):
    repo_class = detect_local_repo(root)
    if repo_class is None:
        return None
    return repo_class(root)

def detect_local_repo(root):
    for folder, repo_class in LOCAL_REPOS.items():
        if os.path.isdir(os.path.join(root, folder)):
            return repo_class
    return None

class ProcessError(Exception):
    pass

def clean_call(*run, **kwargs):
    max_status = kwargs.pop('max_status', 0)
    pipe = kwargs.pop('pipe', False)
    result = None

    env = dict(os.environ, LANG='en-us')

    if pipe:
        kwargs.setdefault('universal_newlines', True)
        kwargs.setdefault('stdout', PIPE)
        kwargs.setdefault('stderr', STDOUT)
        env['NOPROMPT'] = 'True'

    if env != os.environ:
        kwargs.setdefault('env', env)

    process = Popen(run, **kwargs)

    if pipe:
        result = process.communicate()[0]

    status = process.wait()
    has_error = pipe and 'connection closed by remote host' in result.lower()

    if status < 0 or status > max_status or has_error:
        message = '!!!!!!!!!!!!!!!!!!!!!!!!!\n' \
                  'Error while calling {}. Aborting (status {}).\nRan: {}\n'.format(
                    run[0], status, run)
        if pipe:
            raise ProcessError(message + result)
        sys.stderr.write(message)
        sys.exit(1)

    if not pipe:
        sys.stdout.write('\n')

    return result

def call_hg(*params, **kwargs):
    result = clean_call(*(['hg'] + list(params)), **kwargs)
    if kwargs.get('pipe'):
        lines = result.split('\n')
        for line in lines[:]:
            if line.startswith('*** failed to import extension'):
                lines.remove(line)
                sys.stderr.write(line)
        result = '\n'.join(lines)
    return result

def call_git(*params, **kwargs):
    if platform.system() == 'Windows':
        kwargs.setdefault('shell', True)
    return clean_call(*(['git'] + list(params)), **kwargs)
