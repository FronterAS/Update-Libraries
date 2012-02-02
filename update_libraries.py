#!/usr/bin/env python

# Copyright (c) 2012, Fronter AS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
# THE POSSIBILITY OF SUCH DAMAGE.

import sys
try:
    import argparse
except ImportError:
    sys.exit("This script needs the argparse module.")
import os
import re
import urllib
import textwrap
from ConfigParser import SafeConfigParser, NoSectionError

# List of repository providers.
# The path_prefix will be concatenated with tarball_path or zipball_path
# to form an url to fetch the archive from. If authorization is needed,
# provide an auth key with a value of "username:password".
PROVIDERS = {
    "github": {
        "path_prefix": "https://github.com/%s",
        "tarball_path": "/tarball/%s",
        "zipball_path": "/zipball/%s"
    },
    "gitorious": {
        "path_prefix": "http://gitorious.org/%s",
        "tarball_path": "/archive-tarball/%s"
    },
    "bitbucket": {
        "path_prefix": "https://bitbucket.org/%s",
        "tarball_path": "/get/%s.tar.gz",
        "zipball_path": "/get/%s.zip"
    }
}


class UpdateLibraries:
    """Update external libraries.

    This class lets you handle external code libraries in a simple and
    streamlined way. External code is downloaded or cloned in a central
    location and symlinked into the projects using it. Thus externals are
    shared between all projects.

    If the external repository has submodules, you need to use a proper clone,
    i.e. type = Repo. All submodules will be updated recursively when the main
    repository is updated.

    It uses a config file with the following format:

        [Library name]
        type = (ProviderTag|Repo)
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
    """

    VERSION = "1.3.0"

    def __init__(self):
        """Initialize object variables."""
        self.args = None
        self.config = None
        self.linkinfo = None

    def __del__(self):
        """Save the linkinfo file."""
        if self.linkinfo:
            try:
                linkinfo_file = open(self._linkinfo_file(), "w")
                self.linkinfo.write(linkinfo_file)
            finally:
                linkinfo_file.close()

    def run(self):
        """Main entry point."""
        self._args()
        if self.args.update:
            self._do_update()
        if self.args.link:
            self._do_unlink()
            self._do_link()

    # Action methods ========================================================

    def _args(self):
        """Parse and get command line arguments."""
        parser = argparse.ArgumentParser(
                description="Update external library dependencies and link them to the project.")
        parser.add_argument(
                "-v", "--version",
                action="version",
                version="Update libraries v. %s" % self.VERSION)
        parser.add_argument(
                "-q", "--quiet",
                action="store_true",
                default=False,
                help="be quiet")
        parser.add_argument(
                "-Q", "--very-quiet",
                action="store_true",
                default=False,
                help="be very quiet")
        parser.add_argument(
                "-e", "--extroot",
                help="path to EXTLIBS_ROOT, or environment variable if not set")
        parser.add_argument(
                "-l", "--libroot",
                help="path to folder for linking, or same folder as ini-file if not set")
        parser.add_argument(
                "-f", "--force",
                action="store_true",
                default=False,
                help="force update of checkouts in EXTLIBS_ROOT")
        parser.add_argument(
                "--no-update",
                dest="update",
                action="store_false",
                default=True,
                help="do not update checkouts")
        parser.add_argument(
                "--no-link",
                dest="link",
                action="store_false",
                default=True,
                help="do not create symlinks")
        parser.add_argument(
                "configfile",
                help="library configuration file")
        self.args = parser.parse_args()

        if not self.args.extroot:
            if 'EXTLIBS_ROOT' in os.environ:
                self.args.extroot = os.environ['EXTLIBS_ROOT']
            else:
                sys.exit(textwrap.dedent("""
                    Missing EXTLIBS_ROOT environment variable.

                    Please add the path for your external libraries to
                    your .bashrc or equivalent:
                    export EXTLIBS_ROOT=CHANGEME
                    """))
        if not os.path.isdir(self.args.extroot):
            sys.exit(textwrap.dedent("""
                The --extroot parameter or EXTLIBS_ROOT environment variable
                does not point to an existing directory. Create the desired
                directory and try again.
                """))
        if not self.args.libroot:
            self.args.libroot = os.path.dirname(
                    os.path.abspath(self.args.configfile))
        if self.args.very_quiet:
            self.args.quiet = True

        self.config = SafeConfigParser()
        self.config.read(self.args.configfile)
        self.linkinfo = SafeConfigParser()
        self.linkinfo.read(self._linkinfo_file())

    def _do_update(self):
        """Create or update checkouts."""
        curdir = os.getcwd()
        for library in self.config.sections():
            tag_or_branch = self._tag_or_branch(library)
            provider = self._type(library)

            if provider == "repo":
                self._fetch_from_repo(library, tag_or_branch)
            elif provider in PROVIDERS:
                self._fetch_from_provider(library, tag_or_branch, provider)
            else:
                self._message("Unknown library type '%s'" % provider)

        os.chdir(curdir)

    def _do_unlink(self):
        """
        Remove all symlinks from previous link pass.
        Also remove empty directories that were left by removing links.
        """
        sect = os.path.abspath(self.args.libroot)
        if self.linkinfo.has_section(sect):
            for index, link in self.linkinfo.items(sect):
                if os.path.islink(link):
                    os.unlink(link)
                try:
                    os.removedirs(os.path.dirname(link))
                except OSError:
                    pass
            self.linkinfo.remove_section(sect)

    def _do_link(self):
        """Create or update symlinks."""
        for library in self.config.sections():
            for from_key, to_key in self._get_links(library):
                link_from = os.path.join(
                        self._extdir_from_library(library),
                        self._tag_or_branch(library),
                        self.config.get(library, from_key))
                link_to = os.path.join(
                        self.args.libroot, self.config.get(library, to_key))

                if not os.path.isdir(os.path.dirname(link_to)):
                    os.makedirs(os.path.dirname(link_to))

                self._message(
                        "Creating symlink from %s to %s"
                        % (link_from, link_to))
                if os.path.islink(link_to):
                    os.unlink(link_to)
                if not os.path.exists(link_to):
                    os.symlink(link_from, link_to)

                sect = os.path.abspath(self.args.libroot)
                try:
                    count = len(self.linkinfo.options(sect))
                except NoSectionError:
                    self.linkinfo.add_section(sect)
                    count = 0
                self.linkinfo.set(sect, str(count + 1), os.path.abspath(link_to))

    # Action helpers ========================================================

    def _get_links(self, library):
        """Extract the link pairs from available library options.

        Pairs are link_from / link_to with an optional numeric suffix.
        We assume that the syntax is correct, i.e. from always has a
        corresponding to.
        """
        links = []
        for link_key in self.config.options(library):
            m = re.match(r"link_from(\.\d+)?", link_key)
            if m:
                if m.group(1):
                    suffix = m.group(1)
                else:
                    suffix = ""
                links.append(("link_from" + suffix, "link_to" + suffix))
        return links

    def _fetch_from_repo(self, library, tag_or_branch):
        url = self.config.get(library, "url")
        progress = ("", "-q")[self.args.quiet]

        if (self._ensure_dir(library, tag_or_branch)):
            msg = "Cloning %s into %s" % (url, tag_or_branch)
            cmd = "git clone %(0)s %(1)s %(2)s && " \
                  "cd %(2)s && git checkout %(0)s %(2)s && " \
                  "git submodule update --init --recursive" \
                % {"0": progress, "1": url, "2": tag_or_branch}
        else:
            msg = "Updating %s from repo %s" % (tag_or_branch, url)
            cmd = "cd %(1)s && git fetch -t %(0)s && git checkout --force %(1)s && " \
                  "git submodule update --init --recursive" \
                % {"0": progress, "1": tag_or_branch}

        self._check_and_run_cmd(cmd, msg)

    def _fetch_from_provider(self, library, tag_or_branch, provider):
        if self._ensure_dir(library, tag_or_branch):
            provider_data = PROVIDERS[provider]
            path_slice = self.config.get(library, "url")
            url_tarball = url_zipball = None
            if "tarball_path" in provider_data:
                url_tarball = provider_data["path_prefix"] + provider_data["tarball_path"]
                url_tarball %= (path_slice, tag_or_branch)
            if "zipball_path" in provider_data:
                url_zipball = provider_data["path_prefix"] + provider_data["zipball_path"]
                url_zipball %= (path_slice, tag_or_branch)
            if "auth" in provider_data:
                auth = "--user %s" % provider_data["auth"]
            else:
                auth = ""
            progress = ("--progress", "--silent")[self.args.quiet]

            if self._check_url(url_tarball):
                ball_url = url_tarball
                ball_type = "tarball"
                cmd = "curl %s %s --insecure --location %s | " \
                      "tar zxf - -C %s --strip-components 1" \
                    % (progress, auth, ball_url, tag_or_branch)
            elif self._check_url(url_zipball):
                ball_url = url_zipball
                ball_type = "zipball"
                cmd = "curl %s %s --insecure --location %s | " \
                      "xargs -0 unzip" \
                    % (progress, auth, ball_url)

            self._check_and_run_cmd(
                    cmd,
                    "Fetching %s %s/%s from %s"
                    % (ball_type, path_slice, tag_or_branch, provider.capitalize()))

    # Local helpers =========================================================

    def _message(self, message):
        """Print status messages."""
        if not self.args.very_quiet:
            print message

    def _type(self, library):
        """Get the library type."""
        return self.config.get(library, "type").lower()

    def _tag_or_branch(self, library):
        """Get the library tag or branch name."""
        if self.config.has_option(library, "tag"):
            return self.config.get(library, "tag")
        else:
            return self.config.get(library, "branch")

    def _extdir_from_library(self, library):
        """Get the extdir path for the given library."""
        url = self.config.get(library, 'url')
        repo_type = self._type(library)
        if repo_type == "repo":
            library_name = url
        else:
            library_name = PROVIDERS[repo_type]["path_prefix"] % url
        return os.path.join(
                self.args.extroot, re.compile("\W").sub("_", library_name))

    def _linkinfo_file(self):
        """Get the path to the linkinfo file."""
        return os.path.join(self.args.extroot, "linkinfo.ini")

    def _ensure_dir(self, library, subdir):
        """Ensure the directory path exists and cd to it."""
        create = True
        extdir = self._extdir_from_library(library)
        path = os.path.join(extdir, subdir)

        if os.path.exists(path):
            if self.args.force:
                self._message("Removing old version of %s" % path)
                os.system("rm -rf %s" % path)
            else:
                self._message("%s already exists" % path)
                create = False

        if create:
            os.makedirs(path)

        os.chdir(extdir)
        return create

    def _check_and_run_cmd(self, cmd, msg):
        """Execute the given command or display error message."""
        if cmd:
            self._message(msg)
            os.system(cmd)
        else:
            self._message("No such url, check %s for errors." % self.args.configfile)

    def _check_url(self, url):
        """Check if a given url points to a valid resource."""
        if not url:
            return False
        if not url.startswith("http"):
            # Always assume non-http urls are correct.
            # This is really wrong and should be refactored.
            return True

        test = urllib.urlopen(url)
        if "status" in test.info():
            status = test.info()["status"]
        else:
            # If no status returned, then urllib says the resource is valid.
            status = "200 OK"

        status = re.search("(\d+)", status)
        return 200 <= int(status.group(1)) < 400


if __name__ == "__main__":
    me = UpdateLibraries()
    me.run()
