import datetime
import subprocess
import os
import argparse
import json
import sys

MAPPATH = '~/.zgit_conf.json'

class ZfsReceiveError(ValueError):
    pass
        

def datesnap_name(dt=None, fmt='%y%m%d%H%M'):
    'get date string for use as snapshot name'
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime(fmt)

def get_snapshot_dict(cmd=['zfs', 'list', '-H', '-t', 'snapshot', '-o',
                           'name,guid,creation,org.zgit:commitmsg'],
                      cmd1=['zfs', 'list', '-H', '-o', 'name']):
    'get dict of file systems each with time-ordered list of snapshots'
    d = {}
    for name in subprocess.check_output(cmd1).split('\n')[:-1]:
        d[name] = [] # create empty entry for each ZFS filesystem
    for s in subprocess.check_output(cmd).split('\n')[:-1]:
        name, guid, creation, commitMsg = s.split('\t')
        if commitMsg == '-':
            commitMsg = None
        fs, snap = name.split('@')
        d[fs].append((snap, guid, creation, commitMsg))
    return d


def find_snapshot(fs, snap, snapshotDict=None):
    'return index of snap in time-ordered list of snapshots for fs'
    if not snapshotDict:
        snapshotDict = get_snapshot_dict()
    snaps = snapshotDict[fs]
    for i, t in enumerate(snaps):
        if t[0] == snap:
            return i, snaps
    raise KeyError

def zfs_send_cmd(zfs, snap, rootcommit=False, snapshotDict=None):
    'get fromsnap, cmd for zfs send zfs@snap'
    newsnap = '%s@%s' % (zfs, snap)
    i, snaps = find_snapshot(zfs, snap, snapshotDict)
    if rootcommit or i == 0: # full send
        return None, ['zfs', 'send', newsnap]
    else: # incremental send
        fromsnap =  snaps[i - 1][0]
        return fromsnap, ['zfs', 'send', '-i', '%s@%s' % (zfs, fromsnap), newsnap]


def zfs_receive_cmd(zfs):
    'get cmd for zfs receive'
#    if not snapshotDict:
#        snapshotDict = get_snapshot_dict()
#    if fromsnap: # make sure this incremental can be applied
#        lastsnap = snapshotDict[zfs][-1][0] # latest snapshot
#        if lastsnap != fromsnap:
#            raise KeyError
#    elif zfs in snapshotDict: # make sure this zfs does not already exist
#            raise ValueError
    return ['zfs', 'receive', zfs]

def sort_sources(srcs, sourceOrder):
    'sort according to sourceOrder, and the remainder alphabetically'
    l = []
    for src in srcs:
        root = src.split('/')[0]
        try:
            l.append((sourceOrder.index(root), src))
        except ValueError:
            l.append((len(sourceOrder), src))
    l.sort()
    return [t[1] for t in l]

def get_snapshot_map(snapshotDict, backupMap, sourceOrder=()):
    'find mapping between zfs filesystems based on shared snapshots'
    guids = {}
    for src, snaps in snapshotDict.items():
        for s in snaps:
            guids.setdefault(s[1], []).append(src)
    snapshotMap = {}
    for guid, srcs in guids.items():
        srcs = sort_sources(srcs, sourceOrder)
        refSrc = srcs[0] # default to lowest order source
        for src in srcs:
            if src in backupMap: # already registered, so use as refSrc
                refSrc = src
                break
        otherSrcs = [src for src in srcs if src != refSrc]
        for src in otherSrcs:
            snapshotMap.setdefault((refSrc, src), []).append(guid)
    return snapshotMap
        

def get_mount_dict(cmd=['zfs', 'list', '-H', '-o', 'name,mountpoint']):
    'get dict of file systems each with mount point'
    d = {}
    for name in subprocess.check_output(cmd).split('\n')[:-1]:
        fs, mountpoint = name.split('\t')
        d[fs] = mountpoint
    return d

def create_snapshot(fs, snap=None, commitMsg=None, cmd=['zfs', 'snapshot']):
    'create the snapshot fs@snap and return its full name'
    if snap is None:
        snap = datesnap_name()
    name = fs + '@' + snap
    if commitMsg:
        cmd = cmd + ['-o', 'org.zgit:commitmsg=%s' % commitMsg]
    subprocess.check_call(cmd + [name])
    return name

def destroy_snapshot(fs, snap, cmd=['zfs', 'destroy']):
    'destroy the snapshot fs@snap'
    name = fs + '@' + snap
    subprocess.check_call(cmd + [name])

def create_filesystem(zfsname, cmd=['zfs', 'create']):
    'create the ZFS filesystem zfsname'
    subprocess.check_call(cmd + [zfsname])

def push_incremental(src, dest, oldsnap, newsnap, cmd='zfs send -i %s %s|zfs receive %s',
                                            readonly=False):
    '''push newsnap as incremental update from old snap to dest filesystem.
    do not use unless SURE args cannot contain shell injection attack'''
    oldname = src + '@' + oldsnap
    newname = src + '@' + newsnap
    try:
        subprocess.check_call(cmd % (oldname, newname, dest), shell=True)
    except subprocess.CalledProcessError:
        if readonly: # retry push by treating dest as readonly archive
            subprocess.check_call(['zfs', 'rollback', dest + '@' + oldsnap])
            subprocess.check_call(['zfs', 'set', 'readonly=on', dest])
            subprocess.check_call(cmd % (oldname, newname, dest), shell=True)
        else:
            raise ZfsReceiveError


def push_root(src, dest, newsnap, cmd='zfs send %s|zfs receive %s'):
    '''push newsnap from src to create dest filesystem.
    do not use unless SURE args cannot contain shell injection attack'''
    newname = src + '@' + newsnap
    subprocess.check_call(cmd % (newname, dest), shell=True)


def dest_zpool_exists(dest, snapshotDict):
    'check whether dest root available, so we can create dest'
    return dest.split('/')[0] in snapshotDict

def create_missing_parents(dest, snapshotDict):
    'ensure that parent filesystems exist'
    l = dest.split('/')
    for end in range(2, len(l)): # don't try to create root or dest!
        parent = '/'.join(l[:end])
        if parent not in snapshotDict:
            create_filesystem(parent)
            snapshotDict[parent] = [] # register repo with no snapshots

def clone_initial_snapshot(src, dest, snapshotDict, cloneSnap=0):
    'copy src[cloneSnap] snapshot to dest and register it'
    print 'Creating %s by cloning initial snapshot...' % dest
    create_missing_parents(dest, snapshotDict) # ensure parents exist
    push_root(src, dest, snapshotDict[src][cloneSnap][0])
    snapshotDict[dest] = [snapshotDict[src][cloneSnap]] # register new clone

def find_ff_start(src, dest, snapshotDict=None, createIfMissing=False,
                  cloneSnap=0):
    'find start point in src to fast-forward update dest'
    if not snapshotDict:
        snapshotDict = get_snapshot_dict()
    srcSnaps = snapshotDict[src]
    srcGUIDs = [t[1] for t in srcSnaps]
    try:
        destSnaps = snapshotDict[dest]
    except KeyError: # dest filesystem does not exist
        if createIfMissing and dest_zpool_exists(dest, snapshotDict):
            clone_initial_snapshot(src, dest, snapshotDict, cloneSnap)
            destSnaps = snapshotDict[dest] = [srcSnaps[cloneSnap]]
        else:
            return [t[0] for t in srcSnaps], None, None, snapshotDict
    destCurrent = destSnaps[-1][1] # last snapshot GUID
    try: # find matching GUID
        ffstart = srcGUIDs.index(destCurrent)
    except ValueError: # HEAD of dest not found in src snapshot history?!
        ffstart = None
    return ([t[0] for t in srcSnaps], [t[0] for t in destSnaps], ffstart,
            snapshotDict)

class CannotFastForwardError(ValueError):
    pass

def update_dest(src, dest, snapshotDict=None, verbose=False,
                createIfMissing=False, readonly=False):
    'push fast-forward update to bring dest up to date with src'
    srcSnaps, destSnaps, i, snapshotDict = find_ff_start(src, dest,
         snapshotDict, createIfMissing)
    if i is None:
        if destSnaps is None:
            if verbose:
                print 'Warning: destination %s is not available' % dest
            return None
        raise CannotFastForwardError('cannot push %s to %s by fast-forward'
                                     % (src, dest))
    return push_ff(src, dest, srcSnaps[i:], readonly=readonly)
    
def push_ff(src, dest, ffSnaps, readonly=False):
    'push incremental snapshots to fast-forward dest to match src'
    head = None
    for i,baseSnap in enumerate(ffSnaps[:-1]):
        head = ffSnaps[i + 1]
        push_incremental(src, dest, baseSnap, head, readonly=readonly)
    return head # report HEAD that was pushed to dest

def sync_ff(src, dest, snapshotDict=None, createIfMissing=False, readonly=False):
    'sync src and dest by fast-forward in either direction'
    if snapshotDict is None:
        snapshotDict = get_snapshot_dict()
    try:
        snap = update_dest(src, dest, snapshotDict,
                           createIfMissing=createIfMissing, readonly=readonly)
        if snap:
            print 'pushed %s@%s to %s' % (src, snap, dest)
    except CannotFastForwardError:
        snap = update_dest(dest, src, snapshotDict,
                           createIfMissing=createIfMissing, readonly=readonly)
        if snap:
            print 'pulled %s@%s to %s' % (dest, snap, src)
    
def read_json_config(path=MAPPATH, autoCreate=True):
    'read config dict'
    path = os.path.expanduser(path)
    try:
        with open(path, 'r') as ifile:
            return json.load(ifile)
    except IOError:
        if autoCreate:
            return dict(backupMap={})
        else:
            raise

def read_json_map(path=MAPPATH, autoCreate=True):
    'get map dict {SRC:[DEST1, DEST2,...], SRC:[DEST1,...]}'
    return read_json_config(path, autoCreate)['backupMap']

def write_json_config(configDict, path=MAPPATH, indent=2):
    'write config dict'
    path = os.path.expanduser(path)
    with open(path, 'w') as ifile:
        json.dump(configDict, ifile, indent=indent)

def write_json_map(backupMap, path=MAPPATH):
    'write backup map dict {SRC:[DEST1, DEST2,...], SRC:[DEST1,...]}'
    path = os.path.expanduser(path)
    configDict = read_json_config(path)
    configDict['backupMap'] = backupMap # update backupMap while retaining other data
    write_json_config(configDict, path)


def add_backup_mapping(src, dest, remote='backup', backupMap=None,
                       snapshotDict=None, deferPush=False, readonly=False):
    'add src -> dest to backupMap, pushing root snapshot if dest does not exist'
    if backupMap is None:
        backupMap = {}
    srcSnaps, destSnaps, i, snapshotDict = find_ff_start(src, dest, snapshotDict)
    if destSnaps is None:
        if deferPush:
            print '''Deferring creation of new ZFS remote %s...
    Note: you MUST provide the --create option to your next zgit sync to create it!''' % dest
        else:
            print 'creating new ZFS remote %s by pushing initial snapshot...' % dest
            push_root(src, dest, snapshotDict[src][0][0])
            if readonly:
                print 'Configuring %s as readonly archive.' % dest
                subprocess.check_call(['zfs', 'set', 'readonly=on', dest])
    backupMap.setdefault(src, []).append((remote, dest))
    return backupMap

def rm_backup_mapping(src, dest, remote=None, backupMap=None):
    'remove specified remote from backupMap'
    if backupMap is None:
        backupMap = read_json_map()
    dests = backupMap[src]
    for i, t in enumerate(dests):
        if t[0] == remote or t[1] == dest:
            del dests[i]
            print 'removed remote', t
            break
    return backupMap
    
def snapshot_sources(backupMap):
    'add new daily snapshot for all entries in backup map'
    for src in backupMap:
        create_snapshot(src)

def backup_sources(backupMap=None):
    'update all backup destinations in backup map'
    if backupMap is None:
        backupMap = read_json_map()
    snapshotDict = get_snapshot_dict()
    for src, dests in backupMap.items():
        for t in dests:
            remote, dest = t
            try:
                snap = update_dest(src, dest, snapshotDict)
                if snap:
                    print 'pushed %s@%s to %s' % (src, snap, dest)
            except CannotFastForwardError:
                print 'Cannot push %s to %s by fast-forward; skipping...' % (src, dest)



def get_zfs_name(mountDict=None, path=None):
    'get filesystem name for path, or current dir if not specified'
    if mountDict is None:
        mountDict = get_mount_dict()
    if path is None:
        path = os.getcwd()
    l = mountDict.items()
    l.sort(lambda x,y:cmp(y[1], x[1])) # ensure long paths first
    for name, mountpoint in l:
        if path.startswith(mountpoint):
            return name
    raise ValueError('%s is not in a ZFS mount' % path)

def get_backup_src(src=None, path=None):
    'make sure path (or CWD if not specified) is in backup map'
    backupMap = read_json_map()
    if not src:
        src = get_zfs_name(path=path)
    if src not in backupMap:
        print '%s not initialized in zgit backup map' % src
        sys.exit(1)
    return src, backupMap


###############################################################
# command line parsing

def get_base_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', help='git-style command to execute')
    return parser



###############################################################
# init command

def init_cmd(path=MAPPATH):
    'initialize empty map'
    backupMap = read_json_map(path)
    src = get_zfs_name()
    do_init(src, backupMap)
    write_json_map(backupMap)

def do_init(src, backupMap):
    if src in backupMap:
        raise ValueError('%s already initialized for zgit --> %s' % (src, backupMap[src]))
    backupMap[src] = [] # no remotes yet
    print 'Initialized %s for zgit' % src


####################################################################
# push command

def get_push_args():
    parser = get_base_parser()
    parser.add_argument('remote', help='name of zgit remote to push to')
    parser.add_argument('branch', help='branch name: either "master" or ZFSNAME')
    parser.add_argument('--readonly', action='store_true', help='mark remote as readonly archive')
    return parser.parse_args()

def push_cmd():
    'push source filesystem to named remote'
    args = get_push_args()
    if args.branch == 'master': # push CWD filesystem
        src = None
    else: # branch specifies zfs name
        src = args.branch
    src, backupMap = get_backup_src(src)
    dest = None
    for remote, zfsname in backupMap[src]:
        if remote == args.remote:
            dest = zfsname
            break
    if not dest:
        print 'no remote named %s' % args.remote
        return 1
    update_dest(src, dest, readonly=args.readonly)


##################################################################
# diff command

def diff_snapshot(src, snaps=(), snapshotDict=None, cmd=['zfs', 'diff', '-H']):
    'get list of changed files vs. snaphot(s)'
    if not snapshotDict:
        snapshotDict = get_snapshot_dict()
    if not snaps:
        snaps = (snapshotDict[src][-1][0],) # diff vs. last snapshot
    args = ['%s@%s' % (src, snaps[0])]
    if len(snaps) > 1:
        args.append('%s@%s' % (src, snaps[1]))
    lines = subprocess.check_output(cmd + args).split('\n')[:-1]
    return [line.split('\t') for line in lines]
    
def get_diff_args():
    parser = get_base_parser()
    parser.add_argument('commits', help='snapshot name(s) to diff',
                        nargs=argparse.REMAINDER)
    return parser.parse_args()

def diff_cmd():
    'print diff vs. snapshot or between 2 snapshots'
    args = get_diff_args()
    src = get_zfs_name()
    diffs = diff_snapshot(src, args.commits)
    print_diffs(diffs)


#################################################################
# status command

def do_status(src, dests=None, nmax=None):
    'list files that changed vs. last commit'
    diffs = diff_snapshot(src)
    print_diffs(diffs)

def print_diffs(diffs, nmax=None):
    'print ZFS diff output as-is'
    for diff in diffs[:nmax]:
        print '\t'.join(diff)
    if nmax and len(diffs) > nmax:
        print '...'

def status_cmd():
    src = get_zfs_name()
    return do_status(src)

def commit_if_changed(src, dests=None, nmax=None,
                      commitMsg='backup latest changes'):
    'if changed, commit and backup'
    try:
        diffs = diff_snapshot(src)
    except subprocess.CalledProcessError:
        print 'WARNING: zfs diff crashed on %s.  Assuming modified.' % src
        diffs = True
    if diffs:
        snap = create_snapshot(src, commitMsg=commitMsg)
        print 'Committed snapshot %s' % snap

#########################################################################
# sync command

def get_sync_args():
    parser = get_base_parser()
    parser.add_argument('--all', action='store_true', help='synchronize all zgit-registered filesystems')
    parser.add_argument('--create', action='store_true', help='create filesystem if missing')
    parser.add_argument('--readonly', action='store_true', help='mark remote as readonly archive')
    return parser.parse_args()

    
def do_syncs(src, dests, nmax=None, createIfMissing=False, readonly=False):
    for t in dests:
        try:
            sync_ff(src, t[1], createIfMissing=createIfMissing, readonly=readonly)
        except CannotFastForwardError:
            print 'Cannot fast-forward either %s or %s.  Recursive merge not yet supported!' % (src, t[1])
        except ZfsReceiveError:
            print 'ERROR: sync skipped. Consider using --readonly option'


##########################################################################
# remote command
    
def get_remote_parser():
    parser = get_base_parser()
    parser.add_argument('subcmd', help='git remote-style command to execute')
    return parser

def get_remote_add_args():
    parser = get_remote_parser()
    parser.add_argument('remote', help='name for new remote')
    parser.add_argument('zfsname', help='ZFS file system name')
    parser.add_argument('--defer', action='store_true', help='do not actually create remote filesystem at this time')
    parser.add_argument('--readonly', action='store_true', help='mark remote as readonly archive')
    return parser.parse_args()

def get_remote_remove_args():
    parser = get_remote_parser()
    parser.add_argument('remote', help='name of remote to delete')
    return parser.parse_args()

def do_remote_add(src, backupMap):
    'zgit remote add command'
    args = get_remote_add_args()
    add_backup_mapping(src, args.zfsname, args.remote, backupMap,
                       deferPush=args.defer, readonly=args.readonly)
    write_json_map(backupMap)
    
def do_remote_remove(src, backupMap):
    'zgit remote remove command'
    args = get_remote_remove_args()
    rm_backup_mapping(src, None, remote=args.remote, backupMap=backupMap)
    write_json_map(backupMap)

def list_remotes(src=None):
    'list name of remote and zfs path'
    backupMap = read_json_map()
    if not src:
        src = get_zfs_name()
    for remote, dest in backupMap.get(src, ()):
        print remote, dest

    
def remote_cmd():
    src, backupMap = get_backup_src()
    if len(sys.argv) > 2 and sys.argv[2] == 'add':
        return do_remote_add(src, backupMap)
    elif len(sys.argv) > 2 and sys.argv[2] == 'remove':
        return do_remote_remove(src, backupMap)
    elif len(sys.argv) == 2:
        return list_remotes()
    else:
        print '''Usage: zgit remote SUBCOMMAND [args] [options]
        where SUBCOMMAND is:
              add REMOTENAME ZFSNAME
              remove REMOTENAME'''
        return 1 # error status

#######################################################################
# map command

def count_divergences(src, dest, snapshotDict):
    'return #commits in src vs. dest after their last shared commit'
    try:
        srcSnaps = snapshotDict[src]
    except KeyError:
        return None, None
    destGUIDs = {}
    for i,t in enumerate(snapshotDict.get(dest, ())):
        destGUIDs[t[1]] = i
    for i in range(len(srcSnaps) - 1, -1, -1): # find last common snapshot
        try:
            j = destGUIDs[srcSnaps[i][1]]
            return len(srcSnaps) - i - 1, len(destGUIDs) - j - 1
        except KeyError:
            pass
    return None, None

def is_remote_dest(src, dest, backupMap):
    'is dest a zgit remote of src?'
    for remote, path in backupMap.get(src, ()):
        if path == dest:
            return True
        
def get_map_args():
    parser = get_base_parser()
    parser.add_argument('--add', action='store_true', help='interactively add to mapping')
    parser.add_argument('--order', type=str, default='',
                        help='comma separated list of ZFS pools to prefer as reference')
    return parser.parse_args()

def add_new_mapping(src, dest, backupMap):
    'add pair to backup mapping, init if needed'
    if src not in backupMap:
        do_init(src, backupMap)
    remoteName = dest.split('/')[0]
    add_backup_mapping(src, dest, remoteName, backupMap)
    write_json_map(backupMap)

def map_cmd():
    'print ZFS content mappings based on snapshot GUIDs intersection'
    args = get_map_args()
    sourceOrder = args.order.split(',')
    backupMap = read_json_map()
    snapshotDict = get_snapshot_dict()
    snapshotMap = get_snapshot_map(snapshotDict, backupMap, sourceOrder)
    mapData = snapshotMap.items()
    mapData.sort(lambda x,y:cmp(len(y[1]), len(x[1]))) # sort longest first
    for pair, snaps in mapData:
        i, j = count_divergences(pair[0], pair[1], snapshotDict)
        if i:
            print '%s is ahead of %s by %d commits' % (pair[0], pair[1], i)
        if j:
            print '%s is ahead of %s by %d commits' % (pair[1], pair[0], j)
        elif i == 0:
            print '%s and %s are in sync (%d shared commits)' \
              % (pair[0], pair[1], len(snaps))
        if not is_remote_dest(pair[0], pair[1], backupMap):
            print '\tNOT yet added as a zgit remote: you can use "zgit remote add" to do so.\n'
            if args.add:
                doAdd = raw_input('Type Y to add now: ')
                if doAdd and doAdd.lower()[0] == 'y':
                    add_new_mapping(pair[0], pair[1], backupMap)


############################################################################
# forget command

def forget_snapshots(src, snapshotDict, keep=4):
    'delete old snapshots keeping only most recent snapshot(s) specified by keep'
    deleteSnaps = snapshotDict[src][:-keep]
    if deleteSnaps:
        print 'deleting %d old snapshots from %s...' % (len(deleteSnaps), src)
    for snapInfo in deleteSnaps:
        destroy_snapshot(src, snapInfo[0])

def get_forget_args():
    parser = get_base_parser()
    parser.add_argument('--keep', type=int, help='number of latest commits to keep', default=4)
    return parser.parse_args()


def forget_cmd():
    'delete all but most recent snapshots in current ZFS filesystem'
    args = get_forget_args()
    snapshotDict = get_snapshot_dict()
    src = get_zfs_name()
    forget_snapshots(src, snapshotDict, args.keep)
    return 0


#####################################################################
# clone command
        
def get_clone_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    cloneP = subparsers.add_parser('clone')
    cloneP.add_argument('--keep', type=int, default=0,
                        help='#most recent commits to clone (or 0 for all)')
    cloneP.add_argument('--many', nargs='*',
                        help='Multiple ZFS paths to clone')
    cloneP.add_argument('--all', action='store_true', 
                        help='Clone all available mappings registered in .zgit_conf.json')
    cloneP.add_argument('origin', nargs='?', default=None,
                        help='ZFS path to clone')
    cloneP.add_argument('dest', nargs='?', default='//',
                        help='path to create new clone')
    return parser.parse_args()

def clone_cmd():
    'clone one or more ZFS repos'
    args = get_clone_args()
    backupMap = read_json_map()
    snapshotDict = get_snapshot_dict()
    if args.all:
        clone_all(args.origin, backupMap, snapshotDict, args.keep)
    elif args.many:
        for src in args.many:
            do_clone(src, args.dest, backupMap, snapshotDict, args.keep)
    elif args.origin:
        do_clone(args.origin, args.dest, backupMap, snapshotDict, args.keep)
    else:
        raise ValueError('You must supply a ZFS path as origin or --many or --all')
    write_json_map(backupMap)
    return 0

def do_clone(src, dest, backupMap, snapshotDict, keep=0, remoteName='origin'):
    'clone a ZFS repo and record it as origin of new copy'
    if dest == '//': # default to basename of origin
        dest = get_zfs_name() + '/' + src.split('/')[-1]
    clone_initial_snapshot(src, dest, snapshotDict, -keep) # pull first snapshot
    update_dest(src, dest, snapshotDict) # update to match src HEAD
    add_backup_mapping(dest, src, remoteName, backupMap) # add src as origin of dest
    
def clone_all(origin, backupMap, snapshotDict, keep=0):
    'clone all available ZFS repos registered in backupMap, filtered by origin if given'
    targets = list(backupMap)
    targets.sort() # ensure parent filesystems before children
    for target in targets:
        if dest_zpool_exists(target, snapshotDict) and target not in snapshotDict: # could create target
            for name, src in backupMap[target]:
                if (not origin or src.startswith(origin)) and snapshotDict.get(src): # available and has at least one snapshot
                    clone_initial_snapshot(src, target, snapshotDict, -keep) # pull first snapshot
                    update_dest(src, target, snapshotDict) # update to match src HEAD
                    break # success, so stop searching

########################################################################
# log command

def log_cmd(fmt='''commit %(guid)s (ZFS snapshot %(snap)s)
Author: %(author)s
Date:   %(creation)s

    %(commitMsg)s
'''):
    'print git-style log of commits'
    src = get_zfs_name()
    snapshotDict = get_snapshot_dict()
    snaps = snapshotDict[src]
    for i in range(len(snaps) - 1, -1, -1):
        snap, guid, creation, commitMsg = snaps[i]
        print fmt % dict(snap=snap, guid=guid, creation=creation,
                         author='(not recorded)', commitMsg=commitMsg)
    return 0


######################################################################
# commit command

def get_commit_args():
    parser = get_base_parser()
    parser.add_argument('-m', '--message', help='commit message')
    return parser.parse_args()

def commit_cmd():
    'git-style commit saves ZFS snapshot'
    args = get_commit_args()
    commitMsg = args.message
    if not commitMsg:
        commitMsg = raw_input('Enter a commit message: ')
    src = get_zfs_name()
    snap = create_snapshot(src, commitMsg=commitMsg)
    print 'Committed snapshot %s' % snap

#########################################################
# top level command line handling

def run_all(func=do_status, **kwargs):
    backupMap = read_json_map()
    for src,dests in backupMap.items():
        status = func(src, dests=dests, nmax=10, **kwargs)
        if status:
            return status
    
            
if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        status = init_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'remote':
        status = remote_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'push':
        status = push_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'diff':
        status = diff_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'status':
        if len(sys.argv) > 2 and sys.argv[2] == '--all':
            status = run_all()
        else:
            status = status_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'backup':
        import lvmgit
        configDict = read_json_config()
        for lvPath in configDict.get('lvmMap', ()):
            lvmgit.do_commit(lvPath, configDict=configDict) # snapshot LVM to ZFS
        status = run_all(commit_if_changed)
        status = run_all(do_syncs)
        #backup_sources()
    elif len(sys.argv) > 1 and sys.argv[1] == 'map':
        status = map_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'clone':
        status = clone_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'log':
        status = log_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'commit':
        status = commit_cmd()
    elif len(sys.argv) > 1 and sys.argv[1] == 'sync':
        args = get_sync_args()
        if args.all:
            status = run_all(do_syncs, createIfMissing=args.create, readonly=args.readonly)
        else:
            src, backupMap = get_backup_src()
            status = do_syncs(src, backupMap[src], createIfMissing=args.create, readonly=args.readonly)
    elif len(sys.argv) > 1 and sys.argv[1] == 'forget':
        status = forget_cmd()
    else:
        print '''Usage: zgit COMMAND [args] [options]
        where COMMAND is:
              init: add this ZFS file system to zgit backup map in %s
              remote: manage remote repos
              push: push to remote
              backup: push all zgit repos to remotes
              sync: sync this (or all) repo(s) with remotes by fast-forward
              clone: clone a repo
              log: list commits in this repo
              commit: commit a snapshot of this ZFS file system
              map: find ZFS filesystems that share common commits
              forget: delete old snapshots in this ZFS file system''' % MAPPATH
        status = 1
    if status:
        sys.exit(status)
        
#    backupMap = read_json_map()
#    snapshot_sources(backupMap)
#    backup_sources(backupMap)
    
