dependency manager
==================
dm allows to combine multiple repositories into a single project repository.
It's an alternative to git submodules, hg subrepositories, and Android's "repo"
repository manager.

You can make changes to dependencies directly within your project repo
and commit and push your changes directly to the reusable package repos.

Why?
----
Traditionally, you have these options:

All packages in one repository
   This is messy because you have to copy code around in order to share it
   between multiple projects. That's error-prone especially because you can't
   utilize your repo's merge logic. You get incorrect or forgotten
   merges and difficult merge conflicts.

One repository per package
   This makes it time-consuming and difficult to setup the project structure
   and all dependencies for the first time. Pulling new changes is a manual
   and time-consuming process, too. Changes to the project structure
   (e.g. a new dependency) require every developer to take action.
   You get misconfigurations and people forgetting to update their project structure.

Subrepositories
   This doesn't deal with building a project structure, old repositories
   aren't cleaned up, and foreign repo formats aren't supported well enough.
   Dependencies are hard-coded based on revisions, so if someone forgets to push
   the dependencies before the project, all clones and pulls will fail.
   Hard-coded revisions need constant updating by hand and they pollute the project's
   history. Subrepositories are too limited and annoying.

How dm works
------------
dm builds a whole project by cloning all dependency repositories and creating
symlinks to build the required project structure.
This allows to run your project directly on the repositories.
Also, all source code changes are done directly on the repositories.

Additionally, dm runs repository commands (pull, push, status, etc.) on all
dependencies in parallel, so working with a multi-repo project feels snappy.

dm supports hg and git repositories and abstracts their differences behind
simple commands.

dm doesn't hard-code dependencies based on revisions, but instead adds a
special branch to all repositories.


Installation
------------
Clone the dm repo and add the repository root folder to the system PATH, so
you can execute dm from everywhere. That's it.


dm usage
--------
The cli is inspired by hg. Instead of typing e.g. ``hg fetch`` you type
``dm fetch`` in order to fetch data from all repositories that belong to the
current project.

Type ``dm help`` on the command line to get an overview of the available
commands.

dm distinguishes between the main project repository and the package repositories which
that project repo depends on.
The project repository is the root folder of your whole project.
All dependencies, i.e. package repositories, of your project are maintained in a folder
named ``.repos`` which is placed in the root folder of your project repository.

Let's see an example.
In the following, we have a sample project which depends on ``django-socialauth``,
``docutils``, and the company-internal utility library ``django-myutils``.
The project also contains several symlinks which are represented by an arrow ("``--->``").
This is what our project's repository structure looks like::

   <project>/
   |-- .hg/
   |-- .repos/
   |   |-- django-socialauth/
   |   |   |-- .hg/
   |   |   |-- socialauth/
   |   |-- docutils/
   |   |   |-- .git/
   |   |   |-- docutils/
   |   |-- django-myutils/
   |   |   |-- .hg/
   |   |   |-- myutils/
   |   |   |-- .deps
   |-- lib/
   |   |-- socialauth/  --->  ../.repos/django-socialauth/socialauth/
   |-- docutils/  --->  .repos/docutils/docutils/
   |-- myutils/  --->  .repos/django-myutils/myutils/
   |-- .deps
   |-- manage.py
   |-- settings.py
   |-- urls.py

The actual dm configuration is done via ``.deps`` files that describe the dependencies
of a repository. A ``.deps`` file must be placed in its repository's root folder.
The main project repository's ``.deps`` file (``<project>/.deps``) has different options
than a package repository's ``.deps`` file (e.g.,
``<project>/.repos/django-myutils/.deps``).
In the next subsections we'll take a look at the two types of ``.deps`` files.
In particular, we'll see the source of the two ``.deps`` files of our sample project.

Note that the ``.deps`` file is optional. If a repository doesn't have such a file,
dm will assume that it doesn't have any dependencies. From that point of view, you could
use dm on arbitrary repositories, as an alternative to hg/git.

Project-wide .deps
__________________

This is what the above project's ``.deps`` file might look like:

.. sourcecode:: ini

    [repos]
    # Format:
    # <project name> = <source URL>
    django-myutils = https://bitbucket.org/test/django-myutils
    django-socialauth = [hg]https://bitbucket.org/test/django-socialauth
    docutils = [git]https://github.com/test/docutils

    [links]
    # Format:
    # <link location> = <path relative to .repos folder>
    lib/socialauth = django-socialauth/socialauth
    docutils = docutils/docutils

There are two allowed sections in a project's ``.deps`` file.

In ``[repos]`` you specify which other repositories belong to this project.
Each entry in the ``[repos]`` section specifies the repository's project name and its
source URL. You can optionally specify the repository type by prefixing the URL with
either ``[hg]`` or ``[git]`` (as shown above). If omitted, the default repository type is
used, which is ``[hg]``. So, both ``django-myutils`` and ``django-socialauth`` would use
hg, while ``docutils`` would use git.

In ``[links]`` you can additionally specify symlinks that should be created.
For example, in the above sample configuration the dm will create a symlink at
``<project>/lib/socialauth`` pointing to
``<project>/.repos/django-socialauth/socialauth``.

As another example, you will often have strange-looking link definitions like
``docutils = docutils/docutils``. This is just a link at ``<project>/docutils`` pointing
to ``<project>/.repos/docutils/docutils``.
See the sample project's tree structure for a more visual representation of this.


Package .deps
_____________

This is what ``django-myutils``' ``.deps`` file might look like:

.. sourcecode:: ini

    [general]
    dependencies = docutils django-socialauth

    [links]
    myutils = django-myutils/myutils

The biggest difference is that package repositories don't have a ``[repos]`` section.
Instead, they can only specify their dependencies in ``[general]`` via a space-separated
``dependencies`` value that merely lists names of other packages. All of those packages
have to be resolved via the project's ``[repos]`` section.

The ``[links]`` section works exactly as in the project repo's ``.deps``.
However, it has a limitation: A package repo's link definitions may only point to folders
within that repo. Links to other repos are disallowed in order to keep package repos
clearly separated from each other.
