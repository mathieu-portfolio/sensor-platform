"""Same-filesystem staging with the dataset parent's normal permissions."""
from contextlib import contextmanager
from pathlib import Path
import shutil
from uuid import uuid4


@contextmanager
def staging_directory(parent):
    # TemporaryDirectory uses mkdir(0700), which installs a restrictive Windows
    # ACL that survives publication by rename. Use normal mkdir permissions so
    # published data inherits access from its dataset (and respects POSIX umask).
    while True:
        staging = Path(parent) / (".ingest-" + uuid4().hex)
        try:
            staging.mkdir()
        except FileExistsError:
            continue
        break
    try:
        yield staging
    finally:
        # After publication this name is absent; never clean the destination.
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass
