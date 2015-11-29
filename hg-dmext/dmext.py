from mercurial import cmdutil, commands, ui, localrepo
from mercurial.node import hex, short
import os, sys

cmdtable = {}
command = cmdutil.command(cmdtable)

root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
for path in os.environ.get('PATH', '').split(os.pathsep):
    if os.path.basename(path) == 'dependency-manager':
        sys.path.append(path)
        break
os.environ['IGNORE_JARACO'] = '1'

from dependencymanager.core import (get_project_root, get_dependencies_root,
    load_repo_config, mapped_branches)
from dependencymanager.repo import DEFAULT_BRANCH

def get_bookmark_map(repo):
    project_root = os.path.abspath(os.path.normpath(get_project_root(repo.root)))
    if repo.root == os.path.abspath(os.path.normpath(project_root)):
        project_repo = repo
    else:
        project_repo = localrepo.localrepository(repo.baseui, project_root)
    branch_map = mapped_branches(DEFAULT_BRANCH, list(project_repo._bookmarks))[1]
    if project_repo is repo:
        branch_map = {k: '___'.join((k, v)) for k, v in branch_map.items()}
    bookmark_map = dict(map(reversed, branch_map.items()))
    return branch_map, bookmark_map

@command('dmbranch')
def dmbranch(ui, repo, **kwargs):
    bookmark_map = get_bookmark_map(repo)[1]
    hexfn = ui.debugflag and hex or short
    parent = repo['.']
    current = repo._activebookmark
    for mark, rev in repo._bookmarks.items():
        if mark == current:
            prefix, label = '*', 'bookmarks.current'
        else:
            prefix, label = ' ', ''
        if mark in bookmark_map:
            mark = '%s (%s)' % (bookmark_map[mark], mark)
        if mark == '@':
            mark = 'master'
        if ui.quiet:
            ui.write("%s %s\n" % mark, label=label)
        else:
            ui.write(" %s %-25s %d:%s\n" % (
                prefix, mark, repo.changelog.rev(rev), hexfn(rev)),
                label=label)

@command('dmupdate')
def dmupdate(ui, repo, branch, **kwargs):
    branch_map = get_bookmark_map(repo)[0]
    name = branch_map[branch]
    if name == DEFAULT_BRANCH:
        name = '@'
    cmdutil.findcmd('update', commands.table)[1][0](ui, repo, name, **kwargs)

@command('dmmerge')
def dmmerge(ui, repo, branch, **kwargs):
    branch_map = get_bookmark_map(repo)[0]
    name = branch_map[branch]
    if name == DEFAULT_BRANCH:
        name = '@'
    cmdutil.findcmd('merge', commands.table)[1][0](ui, repo, name, **kwargs)

if os.environ.get('NOPROMPT') == 'True':
    def get_input(prompt, is_password=False):
        if is_password:
            print('Password required. Probably your password was purged from the '
                  'keystore. Run "hg in" and "hg out" to update the password cache.')
        else:
            print('User input is required to complete this operation:\n\n%s\n\n'
                  'Since stdin is not available the operation was aborted.\n'
                  'You have to complete the operation with hg instead of dm.\n'
                  'Make sure the repository is not in a broken state before you '
                  'continue.' % prompt)
        sys.exit(-1)

    def ui_prompt(self, prompt, default=None):
        get_input(prompt)
    ui.ui.prompt = ui_prompt

    def ui_getpass(self, prompt, default=None):
        get_input(prompt, is_password=True)
    ui.ui.getpass = ui_getpass
