import zgit
import subprocess
import os
import argparse

def add_lv(configDict, lvPath, zfsName, mountDict=None, autoCreate=True):
    'add the specified mapping lvPath --> zfsName, creating ZFS fs if requested'
    if mountDict is None:
        mountDict = zgit.get_mount_dict()
    if zfsName not in mountDict and autoCreate:
        print 'creating filesystem', zfsName
        zgit.create_filesystem(zfsName)
    configDict.setdefault('lvmMap', {})[lvPath] = zfsName

def ensure_dir_exists(path):
    'create directory if it does not exist'
    if not os.path.isdir(path):
        os.mkdir(path)

def create_lvm_snapshot(lvPath, snap=None, snapSize=None,
                        cmd=['lvcreate', '--size', '1G', '-s', '-n']):
    'create an LVM snapshot and return its path'
    if snapSize: # set the snapshot size
        cmd = list(cmd) # copy to prevent side effects
        cmd[2] = snapSize
    if snap is None:
        snap = zgit.datesnap_name()
    subprocess.check_call(cmd + [snap, lvPath]) # take the LVM snapshot
    lvSnapPath = os.path.join(os.path.dirname(lvPath), snap)
    return lvSnapPath

def cp_snapshot_to_zfs(lvSnapPath, zfsPath, zfsName, snap=None, mountDir='/root/zgit',
                       mountCmd=['mount', '-o', 'ro'],
                       rsyncCmd=['rsync', '-a', '--delete'], **kwargs):
    'copy an LVM snapshot to ZFS snapshot'
    if snap is None:
        snap = os.path.basename(lvSnapPath)
    ensure_dir_exists(mountDir)
    mountPoint = os.path.join(mountDir, snap)
    ensure_dir_exists(mountPoint)
    subprocess.check_call(mountCmd + [lvSnapPath, mountPoint]) # mount it read-only
    print 'copying snapshot from %s --> %s' % (lvSnapPath, zfsName)
    subprocess.check_call(rsyncCmd + [mountPoint + '/', zfsPath]) # rsync to ZFS
    zfsSnap = zgit.create_snapshot(zfsName, snap, **kwargs)
    subprocess.check_call(['umount', mountPoint]) # unmount LVM snapshot
    os.rmdir(mountPoint) # rm temporary snap mountpoint
    return zfsSnap

def destroy_lvm_snapshot(lvSnapPath, destroyCmd=['lvremove', '-f']):
    'permanently delete this LVM snapshot'
    subprocess.check_call(destroyCmd + [lvSnapPath])

def commit(lvPath, zfsPath, zfsName, snap=None, commitMsg=None, snapSize=None,
           keepLvmSnap=False, **kwargs):
    'save snapshot of LVM logical volume to ZFS'
    if snapSize: # user passed explicit reservation
        keepLvmSnap = True
    lvSnapPath = create_lvm_snapshot(lvPath, snap, snapSize)
    zfsSnap = cp_snapshot_to_zfs(lvSnapPath, zfsPath, zfsName, snap,
                                 commitMsg=commitMsg, **kwargs)
    if not keepLvmSnap: # delete LVM snapshot
        destroy_lvm_snapshot(lvSnapPath)
    return zfsSnap

def do_commit(lvPath, zfsName=None, configDict=None, snap=None, commitMsg=None,
              mountDict=None, **kwargs):
    'save snapshot of LVM logical volume to associated ZFS'
    if not zfsName:
        if configDict is None:
            configDict = zgit.read_json_config()
        try:
            zfsName = configDict['lvmMap'][lvPath]
        except KeyError:
            raise KeyError('lvPath %s not in lvmMap' % lvPath)
    if mountDict is None:
        mountDict = zgit.get_mount_dict()
    zfsPath = mountDict[zfsName]
    return commit(lvPath, zfsPath, zfsName, snap, commitMsg, **kwargs)

    
def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', help='git-style command to run')
    parser.add_argument('-m', '--message', help='commit message')
    parser.add_argument('--lvmpath', help='LVM logical volume path')
    parser.add_argument('--zfsname', help='ZFS filesystem name')
    parser.add_argument('--size', help='LVM snapshot reservation size')
    return parser.parse_args()

def commit_cmd(args):
    configDict = zgit.read_json_config()
    commitMsg = args.message
    if not commitMsg:
        commitMsg = raw_input('Enter a commit message: ')
    if args.lvmpath:
        lvPath = args.lvmpath
        zfsName = configDict['lvmMap'][lvPath]
    else:
        if args.zfsname:
            zfsName = args.zfsname
        else:
            zfsName = zgit.get_zfs_name()
        for lv,z in configDict['lvmMap'].items():
            if z == zfsName:
                lvPath = lv
                break
        try:
            lvPath
        except NameError:
            raise ValueError('%s not mapped to any LVM logical volume'
                             % zfsName)
    do_commit(lvPath, zfsName, commitMsg=commitMsg, snapSize=args.size)

def init_cmd(args):
    'add a new LVM logical volume -> ZFS filesystem mapping'
    configDict = zgit.read_json_config()
    if not args.lvmpath or not args.zfsname:
        raise ValueError('--lvmpath and --zfsname required for init!')
    add_lv(configDict, args.lvmpath, args.zfsname)
    zgit.do_init(args.zfsname, configDict['backupMap'])
    zgit.write_json_config(configDict) # save new mapping
    
if __name__ == '__main__':
    args = get_args()
    if args.command == 'commit':
        commit_cmd(args)
    elif args.command == 'init':
        init_cmd(args)
    else:
        print '''Usage: lvmgit COMMAND [args] [options]
        where COMMAND is:
              commit: commit a snapshot of this LVM file system'''
