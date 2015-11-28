#!/usr/bin/env python
import ctypes
import os
import platform
import sys
import traceback

# A few Windows constants
SW_HIDE = 0
SW_SHOWNORMAL = 1

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Add support for Windows symbolic links
if platform.system() == 'Windows':
    from jaraco.windows.filesystem import patch_os_module
    patch_os_module()

def escape_param(param):
    return '"%s"' % param.replace('"', r'\"')

def ensure_privileges():
    # Elevates UAC priviledges if we're on Windows
    if platform.system() != 'Windows':
        return
    if int(platform.version().split('.')[0]) < 6:
        sys.stderr.write('This script does not support Windows XP or older Windows '
                         'versions.\n')
        sys.exit(1)
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    ShellExecuteA = ctypes.windll.shell32.ShellExecuteA
    params = ' '.join(map(escape_param, sys.argv))
    result = ShellExecuteA(None, 'runas', sys.executable, params, None, SW_SHOWNORMAL)
    if result != 42:
        sys.stderr.write('Error: Admin access is required to create symbolic links.\n')
    sys.exit(int(result != 42))

ensure_privileges()

def pairs(sequence):
    if len(sequence) % 2:
        raise ValueError('The given list must contain a multiple of two '
                         'elements')
    return zip(sequence[::2], sequence[1::2])

def main():
    try:
        kwargs = {}
        if platform.system() == 'Windows':
            kwargs = {'target_is_directory': True}

        cwd = os.getcwdu()
        for link_name, target in pairs(sys.argv[1:]):
            short_name = os.path.abspath(link_name)[len(cwd) + 1:]
            print('Creating link from %s to %s' % (short_name, target))
            os.symlink(target, link_name, **kwargs)
    except:
        if platform.system() == 'Windows':
            traceback.print_exc()
        else:
            raise
    finally:
        if platform.system() == 'Windows':
            raw_input('Press enter to close')

if __name__ == '__main__':
    main()
