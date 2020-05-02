import itertools, numpy, logging, typing
import matplotlib.pyplot as plt
from dataclasses import dataclass

from lib.code import CodeParser, CodeDep
from lib.fs import FSScanner, FSData
from lib.puml import PumlParser, PumlData, PumlRule

import lib.logging as log


class ArchAnalyzer:
    def __init__(self, log_level: int = logging.DEBUG):
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        )

    # def code_dump(self, compdb: str):
    #   code_data: CodeData = CodeParser(None, True).get_deps(compdb)

    def analyze(self, puml_file, compdb: str, base_dir: str = "."):
        fs_data: FSData = FSScanner(base_dir).scan()
        print(fs_data.root)
        for i in fs_data.index.values():
            print(i.id, " : ", i.full_path)

        puml_data: PumlData = PumlParser(base_dir, fs_data).parse_puml(puml_file)
        # print(puml_data)

        code_deps: CodeDep = CodeParser(fs_data).get_deps(compdb)
        # print(code_data.deps[0])

        rule_matrix = numpy.ones((len(fs_data.index), len(fs_data.index)))

        for rule in puml_data.rules:
            rule_matrix[(rule.src.fs_id, rule.dst.fs_id)] = 0

        for group in puml_data.fs_groups:
            # for each permutation or combination of the filesystem groupings
            for x, y in itertools.combinations(group, 2):
                rule_matrix[(x, y)] = 0
                rule_matrix[(y, x)] = 0
        print("ALL RULES")
        # for rule in rule_matrix:
        #     print(rule)

        dep_dict: Dict[Tuple[int, int], List[CodeDep]] = {}
        dep_matrix = numpy.zeros((len(fs_data.index), len(fs_data.index)))
        for code_dep in code_deps:
            dep_dict.setdefault((code_dep.src.fs_id, code_dep.dst.fs_id), []).append(
                code_dep
            )
            dep_matrix[(code_dep.src.fs_id, code_dep.dst.fs_id)] += 1

        print("ALL DEPS")
        # for dep in dep_matrix:
        #     print(dep)

        print("VIOLATIONS")
        violations_matrix = rule_matrix * dep_matrix
        # for violation in violations_matrix:
        #     print(violation)

        violations = numpy.transpose(numpy.nonzero(violations_matrix))
        code_dep_violations = []
        for violation in violations:
            code_dep_violations.extend(dep_dict[tuple(violation)])

        print(f"TOTAL VIOLATIONS = {len(code_dep_violations)}")
        # # TODO: need to loop through fs_groups
        # if dep[0] == dep[1] or (
        #     dep[0] in puml_data.fs_groups and dep[1] in puml_data.fs_groups
        # ):
        #     continue
        #     if dep in rules:
        #         print("FINE: ", dep)
        #     else:
        #         print("VIOLATION:", dep)
        #         print(code_dep.src.code_node, " --> ", code_dep.dst.code_node)
        # print("DEPS: ", code_fs_id_deps)
