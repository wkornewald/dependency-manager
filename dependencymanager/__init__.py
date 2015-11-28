# Add support for Windows symbolic links
import os, platform
if 'IGNORE_JARACO' not in os.environ and platform.system() == 'Windows':
    from jaraco.windows.filesystem import patch_os_module
    patch_os_module()
