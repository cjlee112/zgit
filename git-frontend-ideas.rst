#################################
Zgit git hooks ideas
#################################

Using Git as Zgit's front-end
-------------------------------------------------

This could have some nice advantages especially for managing sync:

* use git tools such as gitg to view and manage commits, sync etc.
* use git protocols and tools for working with remote servers
* git hooks can entirely automate this
* looks like a nice way to keep and sync a database of commit history, especially about remotes

Basic ideas
-------------------------

* database files presumably would be kept as pretty-printed JSON (one key per line, sorted, with indentation), so Git can diff and merge them transparently

* each server keeps **zgit-map** repo (Git repo) that keeps the database of the GUID list for all known zfs repos.  Your local zgit-map repo would be automatically sync'd with the central "master"

  * **zfsrepos.json**: info about all known zfs repos, including properties such as clone-parent, readonly etc., and its list of snapshot GUIDs
  * **snapshots.json**: useful info about each snapshot, e.g. hash or digital signature for validating it.  Digital signatures aren't needed for an initial proof-of-concept, of course.
  * **submodules**: these represent zgit repos that we actually want to checkout locally.
  * gitrepos (untracked): alternatively it needs a list of local git repos that track the zfsrepos
  * **transports.json** (untracked): mechanisms for sending and receiving zfs-send files.  This basically would be a command to run for send (and another for receive).  People could plug in a full ssh-as-root zfs send / receive (though to me that seems scary for security), or simply enable scp of the zfs-send files to a restricted account.
  * **security.json**: store public keys of different users.

* each zgit repo has an associated git repo
* probably add GUID as tag on each commit.  Though this will probably look ugly in gitg (or other GUI), because it will display a big ugly number tag on every commit.
* definitely would make sense to store the Git commitID as metadata in the ZFS snapshot.
* each such git repo stores the following files:

  * FILES: probably just ls -lR of the zfs snapshot.  Hmm, actually better to make a custom line-format containing exactly the data we need for 3-way merges, e.g. file path, hash, merge-driver-type (e.g. text/line), permissions, timestamp etc.  Note that we don't have to run any kind of ls -R scan at each commit, because zfs diff knows exactly what files changed, hence we only need to update the data for just those changed files.

  * mounts.json (UNTRACKED): dict of named-branch mountpoint(s) -- by default, HEAD.  This would be used by post-checkout hook to automatically do the right unmount / mount steps for your checkout operation

  * probably also directly provide mount point(s) inside the git repo, e.g. as HEAD or branch-name.  If the mount already exists just make symbolic link to it.  Otherwise it can automatically mount your checkout on HEAD.

* one zgit aspect doesn't fit well in the context of Git: zgit forget.  I guess this is one command you would continue to run exactly as I do it now (zgit forget, within the zfs repo). Note that commands like git-prune and git-gc are NOT analogous to zgit forget (and also lack hooks for extending them).


Zgit transport service?
----------------------------------

We might want to create our own transport service, because

* it doesn't make sense to embed zfs-send files in Git repos (wastes space permanently)
* staging a bunch of zfs-send files in an sftp server forces us to create an additional layer of complexity to interface this staging area with the ZFS backend
* working directly with the ZFS backend is quite easy, and zgit already has code to do all that.
* git supplies hooks that would cover both send and receive with this transport service.  Specifically, post-checkout would retrieve any snapshots it needs, and pre-push would send snapshots.
* we only need TWO critical security safeguards: data must be **encrypted** in transport so that only the intended recipient can read it; fetch and push requests must be **digitally signed** to validate whether the request is authorized for this user.




What Git commands have hooks for automation?
---------------------------------------------------------------------

Client side:

* commit
* rebase
* checkout / clone
* merge / pull
* push
* gc
* difftool / mergetool

Server side:

* receive
* update

**Everything else lacks hooks**, e.g. branch, reset, fetch, status, init, log etc.

The lack of a fetch-hook means you cannot decouple ZFS snapshot retrieval (fetch) from checkout (merge) -- the only hook you've got is **git pull**.  One possible solution to this issue is to somehow do a git push to our local repo, which can then run receive/update hooks to do the fetch.  But to start with, zgit repos are all on "master" branch, so git pull is in fact all you need.




What Git submodule commands must trigger Zgit actions?
------------------------------------------------------------------------------------

* **commit**: must create ZFS snapshot and save to ZGITMAP
* **checkout**: must 




Git Submodule Hooks to Use
-----------------------------------------

* **pre-commit**: at a minimum, this must update the FILES list, and take the new zfs snapshot for this commit via our existing zgit commit code.

* **post-commit**: save the new commitID:GUID mapping and add to ZGITMAP/snapshots.json

* **post-checkout**: "fast-forward" ZFS to the specified commit.  Depending on the situation, this can be done via unmount/mount on local HEAD mountpoint, or zfs rollback/receive.  It would need to handle cases where we need to zfs clone to create a ZFS branch associated with this git branch.

  Note that if the checkout requires a remount that fails (because user is "in" the mounted filesystem), print an error message explaining what the user must do (cd to the submodule git repo, out of the mounted filesystem, and repeat the checkout).

* **pre-push**: this would use whatever ZFS transport is configured to send the desired branch to the remote, and update ZGITMAP/snapshots.json.  It could potentially check remote for merge conflict and abort accordingly.

* **merge-driver**: this is not a hook, but a [merge] configuration.  If there is a collision in the FILES list (i.e. same file modified on both branches), our merge-driver script will get called.  See https://github.com/Praqma/git-merge-driver

* **diff-driver**: this is not a hook, but a [diff] configuration.

* **post-merge** (for local git pull): this would use whatever ZFS transport is configured to get the desired branch from the remote, and update ZGITMAP/snapshots.json.  It would then call the same machinery as post-checkout to fast-forward ZFS to the new HEAD.

* **pre-rebase**: it would be kind of mind-blowing if zgit could rebase ZFS branches, but that seems like something that can wait till power-users ask for it.


ZGITMAP Hooks to Use
-------------------------------------

TODO


An example Zfsgit session
-----------------------------------------

Setting up the initial zfsgit ROOT repo::

  $ zfsgit map --create
  Created top-level repository in /home/user/zfsgit
  Mapping Zpool evo970...
  Mapping Zpool mini2tb...
  Created submodule /home/user/zfsgit/home
  Created submodule /home/user/zfsgit/Maildir
  Created submodule /home/user/zfsgit/base19
  Created submodule /home/user/zfsgit/bigdata

Adding a remote::

  $ cd ~/zfsgit
  $ git remote add ts140 ssh://git@TS140:2222/git-server/repos/zfsgit.git
  $ git pull ts140 master

Working with an actual ZFS repository to push and pull from remotes::

  $ cd bigdata
  $ git remote -v
  mini2tb    /mini2tb/zfsgit/genomics/bigdata.git
  ts140   ssh://git@TS140:2222/git-server/repos/zfsgit/bigdata.git
  $ git checkout -b newbranch
  Created ZFS evo970/zfsgit/genomics/bigdata/newbranch branched from evo970/genomics/bigdata
  Mounted now on /home/user/zfsgit/bigdata/HEAD
  $ cd HEAD
  # run lots of computations...
  $ git commit -m 'made a major breakthrough by doubling the search depth'
  $ git push mini2tb newbranch
  Pushed newbranch to mini2tb/zfsgit/genomics/bigdata/newbranch
  $ git pull ts140 master
  Merged 

Push all updates the zfsgit ROOT repo knows about::

  $ cd ~/zfsgit
  $ git push mini2tb

Pull all updates the ts140 zfsgit repo knows about::

  $ git pull ts140 master



Simple merge strategy?
----------------------------------

git merge at the level of a submodule will work beautifully, because FILES list provides all the info needed to identify collisions, and git-merge-driver configuration enables us to script exactly how to perform the merge on the ZFS filesystem.

3-way merge provides a sensible baseline strategy:

* say A is the Most Recent Common Ancestor of B and C.
* find the set of files that changed A->B and A->C
* automatically merge non-colliding changes from the two changed-file lists
* file collisions get raised to the next level of merge strategy.
* for example, line-formatted text files can be merged in the usual Git way
* collisions that have no auto-merge rule get raised as conflicts requiring manual resolution, same as in Git.


