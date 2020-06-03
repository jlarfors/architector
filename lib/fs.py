import os

from dataclasses import dataclass, field
from typing import Dict, List
from numba import jitclass, typeof

from .counter import Counter
from .logging import log_with

import lib.logging as log

logger = log.get_custom_logger(__name__)


@dataclass
class FSEntry:
    id: int
    name: str
    full_path: str
    is_dir: bool
    children: List["FSEntry"] = field(default_factory=lambda: [])


@dataclass
class FSData:
    index: Dict[int, FSEntry] = field(default_factory=lambda: {})
    file_index: Dict[str, FSEntry] = field(default_factory=lambda: {})
    root: FSEntry = None

    def _add_fs_entry(self, fs_entry: FSEntry, parent: FSEntry):
        self.index[fs_entry.id] = fs_entry
        self.file_index[fs_entry.full_path] = fs_entry
        if parent is not None:
            parent.children.append(fs_entry)

    def add_fs_entry(
        self, id: int, name: str, full_path: str, is_dir: bool, parent: FSEntry
    ) -> FSEntry:
        fs_entry = FSEntry(id=id, name=name, full_path=full_path, is_dir=is_dir)
        self._add_fs_entry(fs_entry=fs_entry, parent=parent)
        return fs_entry

    def get_desc_ids(self, id: int, desc: List[int]):
        """
        Given a Filesystem ID, return all the IDs of descendents
        """
        desc.append(id)
        fs = self.index[id]
        for entry in fs.children:
            self.get_desc_ids(entry.id, desc)

    def get_full_path_by_id(self, id: int):
        return self.index[id].full_path

    def get_id_by_path(self, path: str):
        """
    Returns the id of the fs, or None if no matching file is found
    """
        if os.path.exists(path):
            for fs in self.index.values():
                if os.path.samefile(path, fs.full_path):
                    return fs.id
        return None


class FSScanner:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.counter = Counter()
        self.fs_data = FSData()
        self.file_extensions = (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp")
        self.excludes = ["/build", ".git", "/tools/"]

    def _entry_filter(self, entry: os.DirEntry):
        return (
            entry.is_dir() or entry.name.lower().endswith(self.file_extensions)
        ) and not any(exclude in entry.path for exclude in self.excludes)

    def _walk_directory(self, cur_dir: str, parent: FSEntry = None):
        for entry in os.scandir(cur_dir):
            if self._entry_filter(entry):
                fs_entry = self.fs_data.add_fs_entry(
                    id=self.counter.get(),
                    name=entry.name,
                    full_path=os.path.realpath(entry.path),
                    is_dir=entry.is_dir(),
                    parent=parent,
                )
                if entry.is_dir():
                    self._walk_directory(entry.path, fs_entry)

    @log_with(logger=logger, name="Scanning file system")
    def scan(self) -> FSData:
        # first handle the base_dir directory
        self.fs_data.root = self.fs_data.add_fs_entry(
            id=self.counter.get(),
            name=os.path.dirname(self.base_dir),
            full_path=os.path.abspath(self.base_dir),
            is_dir=True,
            parent=None,
        )
        # then walk the directory structure
        self._walk_directory(self.base_dir)
        return self.fs_data
