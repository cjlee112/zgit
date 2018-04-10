Zgit: ZFS Version Control Using a Git Commands Schema
======================================================

Many people are familiar with Git as a version control system for source code.  Some people also use it for other kinds of content such as text, because it provides such a comprehensive schema for branching, merging, and collaborating with others, etc.  

Wouldn't it be great if you had that **distributed version control power with any content at any scale**, in short, version control at the level of file systems themselves?  The ZFS next-generation file system actually provides all those capabilities (and a lot more), and is trivial to install on both Linux and Mac OS X.  However, anyone used to Git will perceive that ZFS's standard command set lacks a lot of the convenience commands that make Git so powerful to use (what Git calls "porcelain").  For example, in Git we can push an entire history of commits to a remote repository with a single command like::

  git push origin master

By contrast, ZFS lacks any concept of a "remote repository" or even of a multi-commit history, so you would have to manually inspect the ZFS snapshot list for both repositories to find the differences, then manually send + receive each snapshot from one to the other.  Doing that manually is error-prone and unscalable.  Zgit solves this by simply giving you a Git command interface that runs all those ZFS commands for you transparently by just typing::

  zgit push origin master

If you're familiar with using Git, you can instantly start using Zgit.  But under the hood, every Zgit command is being executed by ZFS, not Git, which means it scales in the same massive way that ZFS does.

Zgit as a Large-Scale Backup System
------------------------------------------

Zgit also provides some extra convenience commands that turn ZFS into a large-scale backup system that is both simple and powerful.  On each system it keeps a map of all local vs. remote ZFS relationships it knows (i.e. ZFS filesystems that share at least one commit), and you can synchronize the entire set of such mappings with a single command, that is guaranteed data-safe (at the current state of development, that means fast-forward merge strategy)::

  zgit sync --all

The "backup" variant of this first commits any pending changes in any of these file systems, meaning that you can do your entire backup with a single command::

  zgit backup

Zgit can instantly discover for you all such ZFS filesystem relationships (i.e. ZFS filesystems that share at least one commit) with a single command::

  zgit map

Adding the --add flag interactively prompts you for whether to add each such discovered relationship to Zgit's backup map::

  zgit map --add

I've used Zgit for several years as my sole data management and backup solution across about 10 zpools totalling around 20 TB containing dozens of ZFS file systems representing independent data repositories, with frequent forced recovery / migration events (laptops have failures more frequently than most of us would like!), and it has saved me every time.

Prerequisites
----------------

* ZFS is trivial to install on Linux or Mac OS X:

  * On Ubuntu/Mint: **sudo apt-get install zfsutils-linux**
  * On Mac OS X: get the installer from https://openzfsonosx.org/

* Python 2.7

A Work-in-progress: current Zgit commands
-----------------------------------------------------

As a personal project, Zgit has been developed to meet my own needs, and currently covers only a subset of the Git command schema:

**zgit COMMAND [args] [options]** where COMMAND is::

              init: add this ZFS file system to zgit backup map in %s
              remote: manage remote repos
              push: push to remote
              backup: push all zgit repos to remotes
              sync: sync this (or all) repo(s) with remotes by fast-forward
              clone: clone a repo
              log: list commits in this repo
              commit: commit a snapshot of this ZFS file system
              diff: list differences vs. specified commit
              map: find ZFS filesystems that share common commits
              forget: delete old snapshots in this ZFS file system

Add a ZFS file system to the Zgit backup map
..............................................

In the usual Git way, you execute **zgit init** within the repo you want to initialize for use with Zgit, e.g.::

  cd /tank/my/zfs/filesystem
  zgit init

This *does not* modify data in this file system at all.  Zgit keeps its backup map in $HOME/.zgit_conf.json.

Clone a remote ZFS file system and register it in the Zgit backup map
.......................................................................

In the usual Git way, the clone will be created within the current working directory, unless you specify what you want the new clone's ZFS name to be.  E.g.::

  cd /tank
  zgit clone owc3tb/work

will create a new ZFS filesystem **tank/work** as a "local repository" with a remote named **origin** (pointing to ZFS filesystem **owc3tb/work**).  Note that this means **tank/work** is created using zfs send/receive, NOT via *zfs clone* (which is not even possible across separate zpools).  This distinction emphasizes that "clone" means something very different in Git's terminology than in ZFS's terminology (zfs clone = git branch).

You can specify a second argument for where the clone should be created::

  zgit clone owc3tb/work tank/bigproject

List the history of commits
..................................

In the usual Git way, this lists the history of the ZFS file system you are currently in (working directory)::

  zgit log

Commit the current filesystem state
........................................

You commit the current state (of all files) in the filesystem you're in, in the usual Git way::

  zgit commit -m 'my commit message'

Note, unlike Git, ZFS uses a text "snapshot name" to specify a commit (rather than exposing its internal commit ID, as Git does).  To follow Git's commit syntax (which does not prompt the user for a "commit name"), Zgit currently assigns a snapshot name that is just a timestamp in the format YYMMDDhhmm (year, month, day, hour, minute).

List remotes
...............

To list the remotes of the ZFS filesystem you are currently in::

  zgit remote

Add a remote
.............

In the usual Git way, you specify the name of the new remote, and the ZFS filesystem name where it resides::

  zgit remote add owc3tb owc3tb/another/project

Delete a remote
.....................

In the usual Git way, you specify the name of the remote you want to delete::

  zgit remote remove owc3tb

Push a branch to a remote
...............................

ZFS's default handling of branches is to automatically mount each branch as a specified ZFS filesystem name.  Hence Zgit can detect what branch you're in simply by what ZFS filesystem you're in.  To push the branch you are currently in, to a remote named "origin", just type::

  zgit push origin master

You can also specify the branch (without having to be within that filesystem)::

  zgit push origin tank/bigproject

List the differences vs. a given commit
...........................................

If you specify no commit argument, it lists differences in the current state of the filesystem vs the most recent commit::

  zgit diff

If you specify one ZFS snapshot name, it lists differences in the current state of the filesystem vs that commit::

  zgit diff 1707051327

If you specify two ZFS snapshot names, it lists differences between those two commits::

  zgit diff 1707051327 1701112111

Auto-discover ZFS repo mappings
.................................

ZFS has an internal GUID for every commit.  Thus Zgit can use the ZFS GUID database to instantly discover which ZFS filesystems share at least one commit (and hence can be synchronized)::

  zgit map

This prints a detailed analysis of ZFS file system pairs that share history.

Auto-discover and interactively add ZFS remote mappings
............................................................

Providing the --add flag make Zgit prompt you whether you wish to add each discovered mapping to the Zgit backup map::

  zgit map --add

For each proposed pair, the first ZFS file system would be added as the "local" repo and the second the "remote".  As in Git, Zgit models local:remote mappings as a one-to-many relation.  Typically, you want the "local" repo to be the main "working" repo on this host, and all other locations of this repo listed as "remotes".

You can tell Zgit which ZFS pool(s) to prefer as local, using the **--order** argument, which must be a comma separated list, e.g.::

  $ zgit.py map --add --order pool1,pool2
  pool2/user/home and owc3tb/work are in sync (70 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/user/Maildir and owc3tb/Maildir are in sync (65 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/user/mail and owc3tb/mail are in sync (54 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/vbox/vault and owc3tb/vbox/vault are in sync (50 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/vbox/email and owc3tb/vbox/email are in sync (47 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/vbox/work and owc3tb/vbox/work are in sync (44 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/vbox/win7 and owc3tb/vbox/win7 are in sync (30 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: n
  pool2/lecture-videos and owc3tb/lecture-videos are in sync (25 shared commits)
  pool2/installers and owc3tb/installers are in sync (8 shared commits)
  pool2/Photos and owc3tb/Photos are in sync (5 shared commits)
  pool2/user/archive/leec and owc3tb/archive/leec are in sync (3 shared commits)
  pool2/Music and owc3tb/Music are in sync (2 shared commits)
  pool1/vbox/email and owc3tb/vbox/email are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/vbox/email for zgit
  pool1/user/Maildir and owc3tb/Maildir are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/user/Maildir for zgit
  pool1/vbox/vault and owc3tb/vbox/vault are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/vbox/vault for zgit
  pool1/user/Maildir and pool2/user/Maildir are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/vbox/work and pool2/vbox/work are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/vbox/work for zgit
  pool1/user/home and pool2/user/home are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/user/home for zgit
  pool1/vbox/email and pool2/vbox/email are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/user/home and owc3tb/work are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/vbox/base and pool2/vbox/base are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/vbox/base for zgit
  pool1/vbox/win7 and pool2/vbox/win7 are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/vbox/win7 for zgit
  pool1/user/mail and pool2/user/mail are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  Initialized pool1/user/mail for zgit
  pool1/vbox/vault and pool2/vbox/vault are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/vbox/base and owc3tb/vbox/base are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/vbox/work and owc3tb/vbox/work are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/vbox/win7 and owc3tb/vbox/win7 are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y
  pool1/user/mail and owc3tb/mail are in sync (1 shared commits)
	NOT yet added as a zgit remote: you can use "zgit remote add" to do so.

  Type Y to add now: y


As you can see, **zgit map --add** greatly eases the task of managing complex sets of file system mappings.

Synchronize the current repo against its remotes
..................................................

For the current ZFS repo, fast-forward it and / or its remotes to bring them into sync::

  zgit sync

Note that at present, this will only apply a fast-forward merge, NOT a recursive merge.  If both local and remote repo have new commits since their most recent shared commit, Zgit will refuse to synchronize them automatically.  At present you have to merge these manually, e.g. using rsync.  On the other hand, this guarantees absolute data-safety for Zgit sync:

* it will only fast-forward a repo by adding new commits that occured since its most recent commit.
* if it contains any uncommitted changes, Zgit sync will again refuse to synchronize it.  At present, you would have to merge these changes manually.
* ZFS validates the receive of each commit BEFORE making any change in the file system visible, hence any problem in the data transfer will cause the entire sync command to refuse to apply any data changes, and exit with an error message.  This will leave both repos unchanged (no data loss).  Conversely, if the sync command completes with no error, then the fast-forward validated successfully.

Basically, you will never lose data using Zgit sync.

Synchronize all repos known to Zgit
....................................

Sync can be run on all repos in the Zgit backup map via::

  zgit sync --all

Again, this is an absolutely data-safe operation, for the reasons described above.

Backup and synchronize all repos known to Zgit
..................................................

The **zgit backup** command simply scans local repos for filesystem changes (since the last commit), and automatically commits them, then performs a zgit sync --all operation::

  zgit backup

Again, this is an absolutely data-safe operation, for the reasons described above.



Prune the commit history
...........................

ZFS filesystems are often used to keep backup history, which need not be permanent.  For example, you could either keep the complete history just on a backup server, and only the most recent few commits on a user's laptop (to save space).  To provide this flexibility (which is not the norm in Git), Zgit provides a "forget" command, e.g. to prune the current ZFS file system history to just the last four commits::

  zgit forget --keep 4

Note that in order for ZFS (and Zgit) to synchronize two repos, they **must share at least one commit**.  Hence, if you prune too aggressively, you can lose the ability to synchronize vs. remote repos.

What about branch, checkout, pull, fetch and merge?
----------------------------------------------------

These could be added, but I haven't yet got around to them.  Here's the situation:

* **git pull**: currently a reasonable workaround is to use **zgit sync**; because sync uses fast-forward only, it is "direction safe", i.e. it will automatically do push (to bring remote up-to-date) or pull (to bring local repo up-to-date), in a way that is strictly "additive", i.e. all pre-existing commits (in both local and remote) will still be there after the sync, and it will refuse to overwrite uncommitted changes on either side.

* **git branch**: ZFS supports arbitrary history branching.  The only complication is that by default ZFS wants to mount each new ZFS branch as a new filesystem mount point (whereas Git hides all but the "current" branch exposed as the working tree).  To keep this as Git-like as possible, Zgit could keep branches unmounted by default (except the branch you switch to using the checkout command).  

* **git checkout**: Switching between branches using a simple ZFS unmount/mount operation would be instant, but presumably would fail if the user was "in" the mounted filesystem when they do the checkout (which is the norm for git users).  This implies two possible modes for checkout:

  * switch the mount (FAST, no data has to be written): the user would have to specify the ZFS repo name, something like::

      zgit checkout oddbranch tank/my/zfs/filesystem

  * in-place rollback/send-receive (slow if it has to send/receive a lot of data).  This is what Git does (rewrite data in the working-tree).  However, this seems much less suited to potentially huge file systems, and fails to make use of the fact that ZFS could do checkouts instantly simply by changing what it mounts.

  For obvious reasons, I prefer mode #1.

* **git fetch**: easy to implement once we decide exactly how zgit keeps branches, since fetch is ordinarily just fast-forward?

* **git merge**: universal merge of all file formats is clearly not a reasonable aim.  Git restricts itself to line-formatted text and barfs on line-diff collisions.  My sense is that the right approach is to break this down into a few manageable categories:

  * for git repos, merge them solely using git fetch.  I.e. just fast-forward respective remote branches on both sides, but do not touch the working trees.

  * for text files use a standard 3-way merge tool (let it decide what to reject as unmergeable collision).

  * for other files, treat each file as the collision object, i.e. only allow fast-forward on a per-file basis; changes to the same file are rejected as an unmergeable collision.


Some Current Zgit Quirks
---------------------------

Zgit also has some quirks that I haven't yet tried to address:

* ZFS requires root access.  For Zgit, that currently means you have to run zgit using sudo (or su).

* since Zgit is run as root, it currently does not bother to record "author" name for each commit.  This should be fixed.

* Currently, I just run the zgit.py script directly (i.e. haven't bothered to write a proper installer yet).  That means I type commands like::

    sudo python /path/to/zgit.py backup

* Currently, I use USB3 external drives rather than SSH as the "transport" for synchronizing data across different computers.  I just plug the external drive into a host, execute the **zgit backup** command (typically takes a few minutes to synchronize the latest changes), then plug the external drive into another host, run **zgit backup**, repeat, back and forth over time.

  I haven't yet bothered to add SSH remote support (this just means running a specified zfs send / receive command over SSH instead of locally.  I wasn't comfortable with allowing SSH as root).  This would be easy to add.

 



