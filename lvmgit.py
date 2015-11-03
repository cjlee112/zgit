import zgit
import subprocess
import os

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

def create_lvm_snapshot(lvPath, snap=None, cmd=['lvcreate', '--size', '1G', '-s', '-n']):
    'create an LVM snapshot and return its path'
    if snap is None:
        snap = zgit.datesnap_name()
    subprocess.check_call(cmd + [snap, lvPath]) # take the LVM snapshot
    lvSnapPath = os.path.join(os.path.dirname(lvPath), snap)
    return lvSnapPath

def cp_snapshot_to_zfs(lvSnapPath, zfsPath, zfsName, snap=None, mountDir='/root/zgit',
                       mountCmd=['mount', '-o', 'ro'],
                       rsyncCmd=['rsync', '-av', '--delete'], **kwargs):
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

def commit(lvPath, zfsPath, zfsName, snap=None, commitMsg=None,
           keepLvmSnap=False, **kwargs):
    'save snapshot of LVM logical volume to ZFS'
    lvSnapPath = create_lvm_snapshot(lvPath, snap)
    zfsSnap = cp_snapshot_to_zfs(lvSnapPath, zfsPath, zfsName, snap,
                                 commitMsg=commitMsg, **kwargs)
    if not keepLvmSnap: # delete LVM snapshot
        destroy_lvm_snapshot(lvSnapPath)
    return zfsSnap

def do_commit(lvPath, configDict=None, snap=None, commitMsg=None, mountDict=None,
              **kwargs):
    'save snapshot of LVM logical volume to associated ZFS'
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

    
