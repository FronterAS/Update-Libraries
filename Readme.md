# Update External Libraries

Git submodules are great and all, but sometimes it is more convenient to use
external libraries that are kept completely separate from the development
code. This Python script makes such a setup easy. It lets you have a central
place where shared code is stored, and a nice way of specifying where to get
that code from within your projects.

It works like this: In your projects you have a `vendor` folder where you keep
a `vendor.ini` file. This file specifies the external libraries yoy want to
use, which version to get, and how to expose the code to your projects. You
call the `update_libraries.py` script with the vendor file as argument and
that's it. The script will fetch the libraries if that hasn't already been
done, and create symbolic links from the shared code to your project.

It can either fetch tarballs or zipballs for a specific branch or tag, or it
can make a proper clone of a git repository. If the external repository has
submodules, you need to use a proper clone, i.e. `type = Repo`. All submodules
will then be updated recursively when the main repository is updated.


## Prerequisites

* Python >= 2.4
* If Python < 2.6, install `argparse` with pip or easy install
* curl
* git

Create a folder somewhere for the shared code, and set the environment
variable `EXTLIBS_ROOT` to point to this folder.

## Usage

    update_libraries.py [-h] [-v] [-q] [-Q] [-e EXTROOT] [-l LIBROOT] [-f]
                        [--no-update] [--no-link]
                        configfile

    Update external library dependencies and link them to the project.

    positional arguments:
      configfile            library configuration file

    optional arguments:
      -h, --help            show this help message and exit
      -v, --version         show program's version number and exit
      -q, --quiet           be quiet
      -Q, --very-quiet      be very quiet
      -e EXTROOT, --extroot EXTROOT
                            path to EXTLIBS_ROOT, or environment variable if not
                            set
      -l LIBROOT, --libroot LIBROOT
                            path to folder for linking, or same folder as ini-file
                            if not set
      -f, --force           force update of checkouts in EXTLIBS_ROOT
      --no-update           do not update checkouts
      --no-link             do not create symlinks

## Config File Format

It uses a config file with sections of the following format, where
*ProviderTag* is one of Github, Gitorious, or Bitbucket. If necessary, you
can easily add more providers, e.g. a Github Enterprise or custom Gitorious
installation.

    [Library name]
    type = (<ProviderTag>|Repo)
    url = (path slice|full repo url)
    tag = <tag name>
    branch = <branch name>
    link_from = <path relative to the library under extroot>
    link_to = <path relative to the libroot>

Multiple link targets can also be used with the syntax

    link_from.1 = ...
    link_to.1 = ...
    link_from.2 = ...

Here's an actual example:

    [Dojo]
    type = Github
    url = dojo/dojo
    tag = 1.7.1
    link_from = .
    link_to = ../public/static/vendor/dojo
