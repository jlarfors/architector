import itertools, os, sys, typing

from collections import defaultdict
from dataclasses import dataclass, field

from lark import Lark
from lark import Token
from lark import Tree

import lib.logging as log
from .counter import Counter
from .logging import log_with
from .fs import FSData, FSEntry


logger = log.get_custom_logger(__name__)


@dataclass
class PumlNode:
    id: int
    type: str
    name: str
    variable: str
    stereotype: str
    children: typing.List["PumlNode"]
    fs_ids: typing.Tuple[int] = None

    def __hash__(self):
        return hash(self.id)


@dataclass
class PumlRel:
    src: str
    dst: str


class PumlTree:
    def __init__(self):
        self.counter = Counter()
        self.puml_rels: typing.List[PumlRel] = []
        self.node_handler = {
            "start": self._handle_node_ignore,
            "title": self._handle_node_ignore,
            "entity": self._handle_node_ignore,
            "body": self._handle_node_ignore,
            "variable": self._handle_node_ignore,
            "stereotype": self._handle_node_ignore,
            "name": self._handle_node_ignore,
            "package": self._handle_node,
            "component": self._handle_node,
            "relationship": self._handle_node_relationship,
        }

    def _get_node_prop(self, node: Tree, prop: str):
        """
    This is some horrible magic that works because of the way the grammar is written.
    The properties are nested and have their own tree that stores the actual value
    in the first child, hence the x.children[0].value, also strip any quotes
    """
        return next(
            (x.children[0].value.strip('"') for x in node.children if x.data == prop),
            None,
        )

    def _get_tree_children(self, node: Tree):
        """
    Returns the children of a tree that we care about
    """
        return list(filter(lambda x: isinstance(x, Tree), node.children))

    def _handle_node_ignore(self, node: Tree):
        return None

    def _handle_node_unknown(self, node: Tree):
        raise Exception("Unknown node type: {0}".format(node.data))

    def _handle_node(self, node: Tree):
        puml_node = PumlNode(
            id=self.counter.get(),
            type=node.data,
            name=self._get_node_prop(node, "name"),
            variable=self._get_node_prop(node, "variable"),
            stereotype=self._get_node_prop(node, "stereotype"),
            children=[],
        )

        return puml_node

    def _handle_node_relationship(self, node: Tree):
        puml_rel = None
        rel_type = node.children[1].type

        if rel_type == "DEP_USES":
            puml_rel = PumlRel(src=node.children[0].value, dst=node.children[2].value,)
        else:
            puml_rel = PumlRel(src=node.children[2].value, dst=node.children[0].value,)
        self.puml_rels.append(puml_rel)

    def _parse_tree(self, node: Tree, parent: PumlNode) -> PumlNode:
        if isinstance(node, Tree):
            puml_node = self.node_handler.get(node.data, self._handle_node_unknown)(
                node
            )
            # print(puml_node)
            if puml_node is not None:
                parent.children.append(puml_node)
            else:
                # set puml_node as the parent, basically skipping this tree
                puml_node = parent
            # only handle children who are of type tree
            for child in self._get_tree_children(node):
                self._parse_tree(child, puml_node)
        else:
            sys.exit("Unknown type: {}".format(node.type))

    @log_with(logger=logger, name="Parsing PlantUML File")
    def parse_puml(self, puml_file: str) -> defaultdict:
        tree = None
        root = None
        with open("./lib/plantuml_grammar.ebnf") as grammar:
            l = Lark(grammar.read())
            with open(puml_file) as puml:
                tree = l.parse(puml.read())
                # set the root node
                root = self._handle_node(tree)
                for child in self._get_tree_children(tree):
                    self._parse_tree(child, root)

        if tree is None:
            sys.exit("Error!")

        return root, self.puml_rels


@dataclass
class PumlRef:
    fs_id: int
    puml_node: PumlNode


@dataclass
class PumlRule:
    src: PumlRef
    dst: PumlRef


@dataclass
class PumlData:
    root: PumlNode = None
    # index by id
    # index: typing.Dict[int, PumlNode] = field(default_factory=lambda: {})
    # index by variable name
    var_index: typing.Dict[str, PumlNode] = field(default_factory=lambda: {})
    # stores groups of filesystem entities, e.g. when a component
    # refers to a source file and a header file
    fs_groups: typing.List[typing.List[int]] = field(default_factory=lambda: [])
    rules: typing.List[PumlRule] = field(default_factory=lambda: [])


class PumlParser:
    def __init__(self, base_dir, fs_data: FSData):
        self.puml_data = PumlData()
        self.base_dir = base_dir
        self.fs_data = fs_data
        self.file_extensions = (".c", ".cc", ".cpp", ".h", ".hpp")

    def _get_node_fs_ids(self, node: PumlNode, parent: PumlNode) -> typing.List[int]:
        fs_ids = []
        # default base directory to find the PumlNode from
        parent_dir = self.base_dir
        if parent and parent.fs_ids:
            # parent will always be a directory
            parent_dir = self.fs_data.get_full_path_by_id(*parent.fs_ids)
        node_path = os.path.join(parent_dir, node.name)
        # possibilities are the existing node_path, or the node_path plus file extensions
        for ext in ["", *self.file_extensions]:
            node_path_ext = node_path + ext
            fs = self.fs_data.file_index.get(os.path.abspath(node_path_ext), None)
            if fs:
                fs_ids.append(fs.id)
        # fs_ids = tuple(filter(lambda x: x, fs_ids))
        if len(fs_ids) == 0:
            raise Exception("Could not get filesystem id for PlantUML Node: ", node)
        return fs_ids

    def _handle_node(self, node: PumlNode, parent: PumlNode):
        # skip nodes which do not have a variable, e.g. node.type: "start"
        if node.variable is None:
            return None
        # create the indices for this node
        # self.puml_data.index[node.id] = node
        self.puml_data.var_index[node.variable] = node
        node.fs_ids = self._get_node_fs_ids(node, parent)
        # print(node.fs_ids)
        if len(node.fs_ids) > 1:
            self.puml_data.fs_groups.append(node.fs_ids)

    def _process_tree(self, node: PumlNode, parent: PumlNode = None):
        """
    This should do two things:
    1. Assign a FileSystem (FS) id to each PumlNode
    2. Create an index in puml_data
    """
        self._handle_node(node, parent)
        for child in node.children:
            self._process_tree(child, node)

    def _get_desc_fs_ids(self, node: PumlNode):
        """
    Returns list of all FileSystem IDs of descendants
    for a given PumlNode
    """
        fs_ids = node.fs_ids
        for child in node.children:
            fs_ids.extend(child.fs_ids)
            fs_ids.extend(self._get_desc_fs_ids(child))
        return fs_ids

    def _create_rules(self, puml_rels: typing.List[PumlRel]):
        for puml_rel in puml_rels:
            # print(puml_rel)
            node_src = self.puml_data.var_index[puml_rel.src]
            node_dst = self.puml_data.var_index[puml_rel.dst]
            # print(node_src.variable, " --> ", node_dst.variable)
            # print(node_src.id, " --> ", node_dst.id)
            # for the grouped filesystem ids, make an individual rule
            fs_ids_src = self._get_desc_fs_ids(node_src)
            fs_ids_dst = self._get_desc_fs_ids(node_dst)
            # print(fs_ids_src)
            # print(fs_ids_dst)
            for x in fs_ids_src:
                for y in fs_ids_dst:
                    self.puml_data.rules.append(
                        PumlRule(
                            src=PumlRef(fs_id=x, puml_node=node_src),
                            dst=PumlRef(fs_id=y, puml_node=node_dst),
                        )
                    )

    @log_with(logger=logger, name="Processing PlantUML File")
    def parse_puml(self, puml_file: str) -> defaultdict:
        # get friendly version of the PlantUML AST and relationships
        root, puml_rels = PumlTree().parse_puml(puml_file)
        self.puml_data.root = root
        self._process_tree(root)
        self._create_rules(puml_rels)
        # self._create_fs_group_rules()
        return self.puml_data
