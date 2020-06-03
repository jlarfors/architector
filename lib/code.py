import logging
import multiprocessing
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, TextIO

from joblib import Parallel, delayed
from clang.cindex import Index
from clang.cindex import CompileCommand
from clang.cindex import CompilationDatabase
from clang.cindex import CompilationDatabaseError
from clang.cindex import Cursor
from clang.cindex import CursorKind
from clang.cindex import TranslationUnit

from .fs import FSData
from .logging import log_with
from .util import UniqueDict

logger = logging.getLogger(__name__)


class CodeNode:
    def __init__(self, cursor: Cursor):
        # self.id = str(cursor.get_usr())
        self.id = cursor.hash
        self.file = os.path.realpath(str(cursor.location.file))
        self.start_line = cursor.extent.start.line
        self.end_line = cursor.extent.end.line
        self.start_col = cursor.extent.start.column
        self.end_col = cursor.extent.end.column
        self.kind = str(cursor.kind)

    def __hash__(self):
        return self.id

    def __repr__(self):
        return "{0}:{1}:{2}:{3}".format(
            self.file, self.start_line, self.start_col, self.kind
        )


@dataclass
class CodeRef:
    fs_id: int
    code_node: CodeNode


@dataclass
class CodeDep:
    src: CodeRef
    dst: CodeRef


@dataclass
class CompCmd:
    """
  Used as a basic class so that it can be pickled, instead of libclang's
  CompileCommand
  """

    filename: str
    cmd: List[str]


class TUParser:
    def __init__(self, fs_data: FSData):
        self.fs_data = fs_data
        self.deps: List[CodeDep] = []

    def _cursor_skip(self, cursor: Cursor):
        # ignore all cursors in system headers
        return cursor.location.is_in_system_header()

    def _cursor_kind_filter(self, cursor_kind: int):
        return (
            503 == cursor_kind or 40 <= cursor_kind <= 50 or 101 <= cursor_kind <= 103
        )
        # CursorKind.INCLUSION_DIRECTIVE.value == cursor_kind or \
        # CursorKind.TYPE_REF.value <= cursor_kind <= CursorKind.VARIABLE_REF.value or \
        # CursorKind.DECL_REF_EXPR.value <= cursor_kind <= CursorKind.CALL_EXPR.value

    def _cursor_filter(self, cursor: Cursor):
        # this is not very omptimized but avoids processing lots of stuff...
        # ignore system header references
        # ignore if reference in the same file
        return (
            cursor.referenced
            and not cursor.referenced.location.is_in_system_header()
            and cursor.referenced.location.file
            and cursor.location.file.name != cursor.referenced.location.file.name
        )

    def _get_cursor_fs_id(self, node_path: str) -> int:
        # fs_id = next((fs.id for fs in self.fs_data.index.values() if os.path.samefile(node_path, fs.full_path)), None)
        fs = self.fs_data.file_index.get(os.path.abspath(node_path), None)
        # if fs_id is None:
        #     raise Exception(f"Unable to get FileSystem ID from node_path {node_path}")
        if fs:
            return fs.id
        return None

    def _create_code_dep(self, cursor, dst_file: str = None):
        node_src = CodeNode(cursor)
        fs_id_src = self._get_cursor_fs_id(node_src.file)
        # logger.debug(f"Created source CodeNode {node_src}")

        if dst_file == None and cursor.referenced is not None:
            if cursor.referenced.location.file is None:
                logger.warn(
                    f"File location not available for referenced cursor kind {cursor.referenced.kind}"
                )
                return
            # set the node_dst by the referenced cursor
            node_dst = CodeNode(cursor.referenced)
            # logger.debug(f"Created destination CodeNode {node_dst}")
            fs_id_dst = self._get_cursor_fs_id(node_dst.file)
        else:
            node_dst = None
            fs_id_dst = self._get_cursor_fs_id(dst_file)
            if fs_id_dst is None:
                # the file is probably outside of the working tree so we don't care
                return

        # check that filesystem IDs are not None
        if fs_id_src is None or fs_id_dst is None:
            raise Exception(
                f"Filsyste IDs could not be retrieved for src node {node_src}. (src, dst) = {(fs_id_src, fs_id_dst)}"
            )
        # create the code dependency
        self.deps.append(
            CodeDep(
                src=CodeRef(fs_id=fs_id_src, code_node=node_src),
                dst=CodeRef(fs_id=fs_id_dst, code_node=node_dst),
            )
        )

    def _handle_cursor(self, cursor: Cursor):
        try:
            # ignore all cursors in system headers
            if self._cursor_skip(cursor):
                return
            for child in cursor.get_children():
                self._handle_cursor(child)
            if self._cursor_kind_filter(int(cursor.kind.value)):
                if cursor.kind == CursorKind.INCLUSION_DIRECTIVE:
                    if cursor.get_included_file():
                        self._create_code_dep(
                            cursor, dst_file=cursor.get_included_file().name
                        )
                    else:
                        logger.warn(
                            "Could not get include file for CodeNode {0}".format(
                                CodeNode(cursor)
                            )
                        )
                elif self._cursor_filter(cursor):
                    # add dependencies
                    self._create_code_dep(cursor)
        except AssertionError as error:
            # Output expected AssertionErrors.
            logger.error("AssertionError: {}".format(error))
        except Exception as exception:
            # Output unexpected Exceptions.
            logger.error(exception)

    def _code_dump(self, cursor: Cursor, depth: int = 0):
        if self._cursor_skip(cursor):
            return
        if self._cursor_kind_filter(int(cursor.kind.value)):
            print("  " * depth, CodeNode(cursor))
        for child in cursor.get_children():
            self._code_dump(child, depth + 1)

    @log_with(logger=logger, name="Print Diagnostics")
    def _print_diagnostics(self, diagnostics) -> bool:
        fail: bool = False
        for diag in diagnostics:
            print(f"Severity: {diag.severity} - {diag}")
            if diag.severity > 3:
                fail = True
        return fail

    # def parse(self, clang_index: Index, total_comp_cmds: int, index: int, comp_cmd: List[str], code_dump: bool):
    def parse(
        self, total_comp_cmds: int, index: int, comp_cmd: CompCmd, code_dump: bool
    ):
        print(f"Parsing source file [{index+1}/{total_comp_cmds}]: {comp_cmd.filename}")
        tu = Index.create().parse(
            None, comp_cmd.cmd, options=TranslationUnit.PARSE_NONE
        )
        if not tu:
            sys.exit("Error parsing file: ", comp_cmd.filename)
        if self._print_diagnostics(tu.diagnostics):
            sys.exit("Check Diagnostics!")
        if code_dump:
            # we are in debug mode
            self._code_dump(tu.cursor)
        else:
            self._handle_cursor(tu.cursor)
        # [print(i) for i in self.deps]
        return self.deps


# def handle_comp_cmd(tu_parser: TUParser, clang_index: Index, total_comp_cmds: int, index: int, comp_cmd: List[str], code_dump: bool):
def handle_comp_cmd(
    tu_parser: TUParser,
    total_comp_cmds: int,
    index: int,
    comp_cmd: CompCmd,
    code_dump: bool,
):
    return tu_parser.parse(total_comp_cmds, index, comp_cmd, code_dump)


class CodeParser:
    def __init__(self, fs_data, code_dump: bool = False):
        # self.deps: List[CodeDep] = []
        self.fs_data = fs_data
        self.code_dump = code_dump

    @log_with(logger=logger, name="Parsing C/C++ Project")
    def get_deps(self, compdb_file: str) -> List[CodeDep]:
        num_cores = multiprocessing.cpu_count()
        # num_cores = 1
        # load the compilation database
        logger.debug(
            f"Creating compilation database from directory {compdb_file} using {num_cores} cores"
        )
        compdb = CompilationDatabase.fromDirectory(compdb_file)
        total_comp_cmds = len(compdb.getAllCompileCommands())

        # clang_index = Index.create()
        custom_args = [
            "-ferror-limit=0",
            "-isystem",
            "/Library/Developer/CommandLineTools/usr/lib/clang/11.0.0/include",
            "-isystem",
            "/Library/Developer/CommandLineTools/usr/include/c++/v1",
            "-isystem",
            "/Library/Developer/CommandLineTools/SDKs/MacOSX10.15.sdk/usr/include",
            "-isystem",
            "/opt/llvm/lib/clang/9.0.1/include",
        ]

        comp_cmds = []
        # get all the compile commands into basic list of list of strings
        for comp_cmd in compdb.getAllCompileCommands():
            comp_args = list(comp_cmd.arguments)
            comp_args.extend(custom_args)
            comp_cmds.append(CompCmd(filename=comp_cmd.filename, cmd=comp_args))

        deps: List[CodeDep] = []

        # nested_deps = Parallel(n_jobs=num_cores, prefer="threads")(
        nested_deps = Parallel(n_jobs=num_cores)(
            delayed(handle_comp_cmd)(
                TUParser(self.fs_data), total_comp_cmds, index, comp_cmd, self.code_dump
            )
            for index, comp_cmd in enumerate(comp_cmds)
        )

        # flatten the nested list of deps
        deps = [dep for deps in nested_deps for dep in deps]
        return deps
