# This software is released under the terms of the GNU GENERAL PUBLIC LICENSE.
# See LICENSE.txt for full details.
# Copyright 2023 Telemarq Ltd

from abc import ABC, abstractmethod
import hashlib
import os
import shutil
import re
import zipfile
import tempfile

from .sql import Table, Query, get_field_indices, sqlite3_connect as sqlite3_connect_with_regex_support

import fs.tempfs


from logging import getLogger
log = getLogger(__name__)


class Error(Exception):
    pass


class FilesystemNotFoundError(Error):
    pass


class FilesystemTypeUnknownError(Error):
    pass


class DeviceSettings:
    def __init__(self, path, settings_filename='_rime_settings.db'):
        self._db_name = os.path.join(path, settings_filename)
        self.conn = sqlite3_connect_with_regex_support(self._db_name)
        self._init_tables()

    def _init_tables(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT, value TEXT)")

    def _get_setting(self, key):
        c = self.conn.cursor()
        c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = c.fetchone()
        if row:
            return row[0]
        else:
            return None

    def _set_setting(self, key, value):
        c = self.conn.cursor()
        c.execute("UPDATE settings SET value=? WHERE key=?", (value, key))
        if c.rowcount == 0:
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

    def is_subset_fs(self):
        return self._get_setting('subset_fs') == '1'

    def set_subset_fs(self, is_subset_fs):
        self._set_setting('subset_fs', '1' if is_subset_fs else '0')

    def is_locked(self):
        return self._get_setting('locked') == '1'

    def set_locked(self, is_locked):
        self._set_setting('locked', '1' if is_locked else '0')


def _ensuredir(pathname):
    dirname = os.path.dirname(pathname)
    if not os.path.exists(dirname):
        os.makedirs(dirname)


class DeviceFilesystem(ABC):
    @classmethod
    @abstractmethod
    def is_device_filesystem(cls, path) -> bool:
        """
        Is this path the root of a filesystem this class can manage?
        """
        return False

    @classmethod
    @abstractmethod
    def create(cls, id_: str, root: str) -> 'DeviceFilesystem':
        """
        Create a new filesystem of this type at 'path'.
        """
        raise NotImplementedError()

    @abstractmethod
    def is_subset_filesystem(self) -> bool:
        """
        Is this a temporary filesystem?
        """
        return False

    @abstractmethod
    def listdir(self, path) -> list[str]:
        """
        As os.listdir().
        """
        return []

    @abstractmethod
    def exists(self, path) -> bool:
        """
        As os.path.exists().
        """
        return False

    @abstractmethod
    def getsize(self, path) -> int:
        """
        As os.path.getsize().
        """
        return 0

    @abstractmethod
    def open(self, path):
        """
        As open().
        """
        return None

    @abstractmethod
    def create_file(self, path):
        """
        As open(path, 'wb').
        """
        return None

    def sqlite3_uri(self, path, read_only=True):
        """
        Return a URI suitable for passing to sqlite3_connect
        """
        params = "?mode=ro&immutable=1" if read_only else ""
        return f"file:{path}{params}"

    @abstractmethod
    def sqlite3_connect(self, path, read_only=True):
        """
        Return an opened sqlite3 connection to the database at 'path'.
        """
        return None

    @abstractmethod
    def sqlite3_create(self, path):
        """
        Create a new sqlite3 database at 'path' and return an opened connection read-write to it.
        """
        return None

    @abstractmethod
    def lock(self, locked: bool):
        """
        Lock or unlock the filesystem. A locked filesystem can't be viewed or written to.
        """
        pass

    @abstractmethod
    def is_locked(self) -> bool:
        """
        Is the filesystem locked?
        """
        return False


class AndroidDeviceFilesystem(DeviceFilesystem):
    def __init__(self, id_: str, root: str):
        self.id_ = id_
        self._fs = fs.osfs.OSFS(root)
        self._settings = DeviceSettings(root)

    @classmethod
    def is_device_filesystem(cls, path):
        return os.path.exists(os.path.join(path, 'data', 'data', 'android'))

    @classmethod
    def create(cls, id_: str, root: str):
        if os.path.exists(root):
            raise FileExistsError(root)

        os.makedirs(root)
        os.makedirs(os.path.join(root, 'data', 'data', 'android'))

        obj = cls(id_, root)
        obj._settings.set_subset_fs(True)
        return obj

    def is_subset_filesystem(self) -> bool:
        return self._settings.is_subset_fs()

    def listdir(self, path):
        return self._fs.listdir(path)

    def exists(self, path):
        return self._fs.exists(path)

    def getsize(self, path):
        return self._fs.getsize(path)

    def open(self, path):
        return self._fs.open(path, 'rb')

    def create_file(self, path):
        _ensuredir(self._fs.getsyspath(path))

        return self._fs.open(path, 'wb')

    def sqlite3_connect(self, path, read_only=True):
        db_url = self.sqlite3_uri(self._fs.getsyspath(path), read_only)
        log.debug(f"Android connecting to {db_url}")
        return sqlite3_connect_with_regex_support(db_url, uri=True)

    def sqlite3_create(self, path):
        syspath = self._fs.getsyspath(path)

        _ensuredir(syspath)
        return sqlite3_connect_with_regex_support(syspath)

    def lock(self, locked: bool):
        self._settings.set_locked(locked)

    def is_locked(self) -> bool:
        return self._settings.is_locked()


class IosDeviceFilesystem(DeviceFilesystem):
    def __init__(self, id_: str, root: str):
        self.id_ = id_
        self.root = root
        self.manifest = sqlite3_connect_with_regex_support(os.path.join(self.root, 'Manifest.db'))
        self.file_table = Table('Files')
        self._settings = DeviceSettings(root)

    @classmethod
    def is_device_filesystem(cls, path):
        return (
            os.path.exists(os.path.join(path, 'Manifest.db'))
            and os.path.exists(os.path.join(path, 'Info.plist'))
        )

    @classmethod
    def create(cls, id_: str, root: str):
        if os.path.exists(root):
            raise FileExistsError(root)

        os.makedirs(root)

        for filename in {'Manifest.db', 'Info.plist'}:
            with open(os.path.join(root, filename), 'wb'):
                pass  # touch the file to ensure it exists

        obj = cls(id_, root)
        obj._settings.set_subset_fs(True)
        return obj

    def is_subset_filesystem(self) -> bool:
        return self._settings.is_subset_fs()

    def sqlite3_connect(self, path, read_only=True):
        db_url = self.sqlite3_uri(os.path.join(self.root, _get_ios_filename(path)), read_only)
        log.debug(f"iOS connecting to {db_url} ({path})")
        return sqlite3_connect_with_regex_support(db_url, uri=True)

    def listdir(self, path):
        query = Query.from_(self.file_table).select('fileID', 'relativePath')
        query = query.where(self.file_table.relativePath == os.path.join(self.root, path))
        fields = get_field_indices(query)
        return [row[fields['relativePath']] for row in self.manifest.execute(str(query))]

    def exists(self, path):
        real_path = _get_ios_filename(path)
        return os.path.exists(os.path.join(self.root, real_path))

    def getsize(self, path):
        return os.path.getsize(os.path.join(self.root, _get_ios_filename(path)))

    def open(self, path):
        # TODO: Should cope with blobs in the manifest too
        return open(os.path.join(self.root, _get_ios_filename(path), 'rb'))

    def create_file(self, path):
        raise NotImplementedError

    def sqlite3_create(self, path):
        """
        Create a new sqlite3 database at the given path and fail if it already exists.
        """
        real_path = _get_ios_filename(path)
        syspath = os.path.join(self.root, real_path)

        if self.exists(syspath):
            raise FileExistsError(path)

        _ensuredir(syspath)

        return sqlite3_connect_with_regex_support(syspath)

    def lock(self, locked: bool):
        self._settings.set_locked(locked)

    def is_locked(self) -> bool:
        return self._settings.is_locked()


class IosZippedDeviceFilesystem(DeviceFilesystem):
    """
    Zipped filesystem of an iOS device. Currently supports only read mode
    for the data.

    The class assumes there is only one directory in the .zip file
    and all the other files are located within that directory.

        file.zip
            |- main_dir
                |- Manifest.db
                |- Info.plist
                |- 7c
                    |- 7c7fba66680ef796b916b067077cc246adacf01d
    """

    @staticmethod
    def get_main_dir(zp: zipfile.ZipFile) -> zipfile.Path:
        """
        Get the main directory from within the zip file. The zip file
        should contain one directory and all other files should be in
        that directory.
        """
        root = zipfile.Path(zp)
        main_dir, = root.iterdir()
        return main_dir

    def __init__(self, id_: str, root: str):
        self.id_ = id_

        # store the path of the root
        self.root = root

        # keep a reference to the tempfile in the object
        self.temp_manifest = tempfile.NamedTemporaryFile(mode='w+b')
        self.temp_settings = tempfile.NamedTemporaryFile(mode='w+b')

        with zipfile.ZipFile(self.root) as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)

            with zp.open(os.path.join(main_dir.name, 'Manifest.db')) as zf:
                self.temp_manifest.write(zf.read())

            with zp.open(os.path.join(main_dir.name, '_rime_settings.db')) as zf:
                self.temp_settings.write(zf.read())

        self.manifest = sqlite3_connect_with_regex_support(self.temp_manifest.name)
        self.file_table = Table('Files')

        settings_dir, settings_file = os.path.split(self.temp_settings.name)
        self._settings = DeviceSettings(settings_dir, settings_file)

    @classmethod
    def is_device_filesystem(cls, path) -> bool:

        if not zipfile.is_zipfile(path):
            return False

        with zipfile.ZipFile(path) as zp:
            # get the main directory contained in the .zip container file
            main_dir = cls.get_main_dir(zp)
            return (
                zipfile.Path(zp, os.path.join(main_dir.name, 'Manifest.db')).exists()
                and zipfile.Path(zp, os.path.join(main_dir.name, 'Info.plist')).exists()
            )

    @classmethod
    def create(cls, id_: str, root: str):
        raise NotImplementedError

    def is_subset_filesystem(self) -> bool:
        return self._settings.is_subset_fs()

    def listdir(self, path) -> list[str]:
        """
        As os.listdir().
        """
        return []

    def exists(self, path) -> bool:
        """
        As os.path.exists().
        """
        real_path = _get_ios_filename(path)

        # open the zipfile stored in `self.root` and find out if it
        # contains the `real_path
        with zipfile.ZipFile(self.root) as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)
            return zipfile.Path(zp, os.path.join(main_dir.name, real_path)).exists()

    def getsize(self, path) -> int:
        """
        As os.path.getsize().
        """
        with zipfile.ZipFile(self.root) as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)
            return zp.getinfo(os.path.join(main_dir, _get_ios_filename(path))).file_size

    def open(self, path):
        """
        As open().
        """
        tmp_copy = tempfile.NamedTemporaryFile(mode='w+b')
        with zipfile.ZipFile(self.root) as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)
            with zp.open(os.path.join(main_dir.name, _get_ios_filename(path))) as zf:
                tmp_copy.write(zf.read())
        return tmp_copy

    def create_file(self, path):
        """
        As open(path, 'wb').
        """
        raise NotImplementedError

    def sqlite3_uri(self, path, read_only=True):
        """
        Return a URI suitable for passing to sqlite3_connect
        """
        params = "?mode=ro&immutable=1" if read_only else ""
        return f"file:{path}{params}"

    def sqlite3_connect(self, path, read_only=True):
        """
        Return an opened sqlite3 connection to the database at 'path'.
        """
        tmp_copy = tempfile.NamedTemporaryFile(mode='w+b')

        with zipfile.ZipFile(self.root) as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)
            with zp.open(os.path.join(main_dir.name, _get_ios_filename(path))) as zf:
                tmp_copy.write(zf.read())

        db_url = self.sqlite3_uri(tmp_copy.name)
        log.debug(f"iOS connecting to {db_url} ({path})")
        return sqlite3_connect_with_regex_support(db_url, uri=True)

    def sqlite3_create(self, path):
        """
        Create a new sqlite3 database at 'path' and return an opened connection read-write to it.
        """
        raise NotImplementedError

    def lock(self, locked: bool):
        self._settings.set_locked(locked)

        # update the settings file back in the zipped file
        # for persistent settings preferenses
        with zipfile.ZipFile(self.root, 'w') as zp:
            # get the main directory contained in the .zip container file
            main_dir = self.get_main_dir(zp)
            with zp.open(os.path.join(main_dir, '_rime_settings.db'), 'w') as zf:
                zf.write(self.temp_settings.read())

    def is_locked(self) -> bool:
        return self._settings.is_locked()


FILESYSTEM_TYPE_TO_OBJ = {
    'android': AndroidDeviceFilesystem,
    'ios': IosDeviceFilesystem,
    'ios-zipped': IosZippedDeviceFilesystem,
}


VALID_DEVICE_ID_REGEX = re.compile(r'^[a-zA-Z0-9_-]+$')


class FilesystemRegistry:
    """
    Maintains a registry of filesystems at 'base_path'.

    Filesystems are distinguished by a key, which is the name of the directory they're in under base_path.
    """
    def __init__(self, base_path):
        self.base_path = base_path
        self.filesystems = self._find_available_filesystems()  # maps key to FS object.

    def __getitem__(self, key):
        return self.filesystems[key]

    def rescan(self):
        self.filesystems = self._find_available_filesystems()

    def _find_available_filesystems(self):
        """
        Return a mapping of key -> filesystem type for each valid filesystem under base_path.
        """
        filesystems = {}

        try:
            for filename in os.listdir(self.base_path):
                path = os.path.join(self.base_path, filename)

                for fs_cls in FILESYSTEM_TYPE_TO_OBJ.values():
                    if fs_cls.is_device_filesystem(path):
                        filesystems[filename] = fs_cls(filename, path)
        except FileNotFoundError:
            log.warning(f"Could not find filesystem directory: {self.base_path}")

        return filesystems

    def create_empty_subset_of(self, fs: DeviceFilesystem, key: str, locked: bool = False) -> DeviceFilesystem:
        """
        Create an empty subset filesystem of the same type as 'fs' named 'key'
        """
        path = os.path.join(self.base_path, key)

        if os.path.exists(path):
            raise FileExistsError(key)

        if not self.is_valid_device_id(key):
            raise ValueError(f"Invalid device ID: {key}")

        self.filesystems[key] = fs.__class__.create(key, path)
        print('locked', locked)
        self.filesystems[key].lock(locked)

        return self[key]

    def is_valid_device_id(self, key):
        return VALID_DEVICE_ID_REGEX.match(key)

    def delete(self, key):
        if key not in self.filesystems:
            raise FileNotFoundError(key)

        shutil.rmtree(os.path.join(self.base_path, key))
        del self.filesystems[key]


def _get_ios_filename(path):
    """
    For iOS filesystems.

    What's the actual filename, relative to root, of the file represented by path?
    'Path' is formed of the app domain, a hyphen, and then the relative path. Examples from Manifest.db:

    domain: AppDomainGroup-group.net.whatsapp.WhatsApp.shared
    relativePath: ChatStorage.sqlite
    path: AppDomainGroup-group.net.whatsapp.WhatsApp.shared-ChatStorage.sqlite

    domain: HomeDomain
    relativePath: Library/SMS/sms.db
    path: HomeDomain-Library/SMS/sms.db
    """

    # TODO: some files are stored in blobs in the manifest. Need to deal with that.
    file_id = hashlib.sha1(path.encode()).hexdigest()
    return os.path.join(file_id[:2], file_id)
