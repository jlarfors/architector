import itertools, numpy, logging
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import Dict, List, Tuple

from lib.code import CodeParser, CodeDep
from lib.fs import FSScanner, FSData, FSEntry
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

    def analyze(self, puml_file: str, compdb: str, base_dir: str = "."):
        fs_data: FSData = FSScanner(base_dir).scan()
        # print(fs_data.root)
        # for i in fs_data.index.values():
        #     print(i.id, " : ", i.full_path)

        puml_data: PumlData = PumlParser(base_dir, fs_data).parse_puml(puml_file)
        # print(puml_data)

        code_deps: List[CodeDep] = CodeParser(fs_data).get_deps(compdb)
        # print(code_data.deps[0])

        rule_matrix = numpy.ones((len(fs_data.index), len(fs_data.index)))

        for rule in puml_data.rules:
            # create list of descendent FileSystem IDs for src and dst
            fs_src_ids: List[int] = []
            fs_dst_ids: List[int] = []
            fs_data.get_desc_ids(rule.src.fs_id, fs_src_ids)
            fs_data.get_desc_ids(rule.dst.fs_id, fs_dst_ids)
            # for all descendent src and dst IDs, create a rule
            for src_id in fs_src_ids:
                for dst_id in fs_dst_ids:
                    rule_matrix[(src_id, dst_id)] = 0

        for group in puml_data.fs_groups:
            # for each permutation or combination of the filesystem groupings
            for x, y in itertools.combinations(group, 2):
                rule_matrix[(x, y)] = 0
                rule_matrix[(y, x)] = 0

        # print("ALL RULES")
        # for rule in rule_matrix:
        #     print(rule)

        dep_dict: Dict[Tuple[int, int], List[CodeDep]] = {}
        dep_matrix = numpy.zeros((len(fs_data.index), len(fs_data.index)))
        for code_dep in code_deps:
            if code_dep.src.fs_id == None or code_dep.dst.fs_id == None:
                print(f"ERROR: code dependency has Filsystem ID None: {code_dep}")
                exit(1)
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
        # for dep in code_dep_violations:
        #     print(dep)

        with open("reports/violations_report.csv", "w") as report:
            for dep in code_dep_violations:
                report.write(f"{dep.src.code_node.file},{dep.dst.code_node.file}\n")

        with open("reports/file_index.csv", "w") as report:
            for fs in fs_data.index.values():
                report.write(f"{fs.id},{fs.full_path}\n")

        fig, ax = plt.subplots()
        im = ax.imshow(violations_matrix)

        ax.xaxis.tick_top()

        fig.tight_layout()
        # plt.savefig('matrix.png', dpi=600)
        # fig.savefig("matrix.png", dpi=600, bbox_inches="tight")
        plt.show()
