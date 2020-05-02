
import os, typing

from .counter import Counter
from .logging import log_with

class Scanner:
  def __init__(self, base_dir: str):
    self.base_dir = base_dir
    self.counter = Counter()
    self.data: dict = {}
    self.file_extensions = (".c", ".cc", ".cpp", ".h", ".hpp")

  def _add_to_data(self, entry):
    self.data[entry["id"]] = entry

  def _process_entry(self, entry: os.DirEntry, is_dir: bool) -> dict:
    return {
      "id": self.counter.get(),
      "name": entry.name,
      "full_path": entry.path,
      "is_dir": is_dir,
    }

  def _walk_directory(self, cur_dir) -> typing.List[dict]:
    for entry in os.scandir(cur_dir):
      if entry.is_dir():
        self._add_to_data(self._process_entry(entry, True))
        self._walk_directory(entry.path)
      else:
        if entry.name.lower().endswith(self.file_extensions):
          self._add_to_data(self._process_entry(entry, False))
  @log_with(name="Scanning file system")
  def scan(self) -> typing.List[dict]:
    self._walk_directory(self.base_dir)
    return self.data