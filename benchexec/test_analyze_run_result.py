# This file is part of BenchExec, a framework for reliable benchmarking:
# https://github.com/sosy-lab/benchexec
#
# SPDX-FileCopyrightText: 2007-2020 Dirk Beyer <https://www.sosy-lab.org>
#
# SPDX-License-Identifier: Apache-2.0

import logging
import sys
import pytest
import types

from benchexec.util import ProcessExitCode
from benchexec.model import Run
from benchexec.result import (
    RESULT_FALSE_REACH,
    RESULT_ERROR,
    RESULT_UNKNOWN,
    RESULT_TRUE_PROP,
)
from benchexec.tools.template import BaseTool

sys.dont_write_bytecode = True  # prevent creation of .pyc files

normal_result = ProcessExitCode(raw=0, value=0, signal=None)

class TestResult:
    def create_run(self, info_result=RESULT_UNKNOWN):
        runSet = types.SimpleNamespace()
        runSet.log_folder = "."
        runSet.result_files_folder = "."
        runSet.options = []
        runSet.real_name = None
        runSet.propertytag = None
        runSet.benchmark = lambda: None
        runSet.benchmark.base_dir = "."
        runSet.benchmark.benchmark_file = "Test.xml"
        runSet.benchmark.columns = []
        runSet.benchmark.name = "Test"
        runSet.benchmark.instance = "Test"
        runSet.benchmark.rlimits = {}
        runSet.benchmark.tool = BaseTool()

        def determine_result(run):
            return info_result

        runSet.benchmark.tool.determine_result = determine_result

        run = Run(
            identifier="test.c",
            sourcefiles=["test.c"],
            task_options=None,
            fileOptions=[],
            runSet=runSet,
        )
        run._cmdline = ["dummy.bin", "test.c"]
        return run

    def test_simple(self):
        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert RESULT_UNKNOWN == run._analyze_result(normal_result, "", None)

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        assert RESULT_TRUE_PROP == run._analyze_result(normal_result, "", None)

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        assert (
            RESULT_FALSE_REACH
            == run._analyze_result(normal_result, "", None)
        )

    def test_timeout(self):
        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert "TIMEOUT" == run._analyze_result(normal_result, "", "cputime")
        assert (
            "TIMEOUT"
            == run._analyze_result(normal_result, "", "cputime-soft")
        )
        assert "TIMEOUT" == run._analyze_result(normal_result, "", "walltime")

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        assert (
            f"TIMEOUT ({RESULT_TRUE_PROP})"
            == run._analyze_result(normal_result, "", "cputime")
        )

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        assert (
            f"TIMEOUT ({RESULT_FALSE_REACH})"
            == run._analyze_result(normal_result, "", "cputime")
        )

        run = self.create_run(info_result="SOME OTHER RESULT")
        assert (
            "TIMEOUT (SOME OTHER RESULT)"
            == run._analyze_result(normal_result, "", "cputime")
        )

        run = self.create_run(info_result=RESULT_ERROR)
        assert "TIMEOUT" == run._analyze_result(normal_result, "", "cputime")

        run = self.create_run(info_result=RESULT_ERROR)
        run._is_timeout = lambda: True
        assert "TIMEOUT" == run._analyze_result(normal_result, "", None)

    def test_out_of_memory(self):
        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert (
            "OUT OF MEMORY"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        assert (
            f"OUT OF MEMORY ({RESULT_TRUE_PROP})"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        assert (
            f"OUT OF MEMORY ({RESULT_FALSE_REACH})"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result="SOME OTHER RESULT")
        assert (
            "OUT OF MEMORY (SOME OTHER RESULT)"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result=RESULT_ERROR)
        assert (
            "OUT OF MEMORY"
            == run._analyze_result(normal_result, "", "memory")
        )

    def test_timeout_and_out_of_memory(self):
        run = self.create_run(info_result=RESULT_UNKNOWN)
        run._is_timeout = lambda: True
        assert "TIMEOUT" == run._analyze_result(normal_result, "", "memory")

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        run._is_timeout = lambda: True
        assert (
            f"TIMEOUT ({RESULT_TRUE_PROP})"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        run._is_timeout = lambda: True
        assert (
            f"TIMEOUT ({RESULT_FALSE_REACH})"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result="SOME OTHER RESULT")
        run._is_timeout = lambda: True
        assert (
            "TIMEOUT (SOME OTHER RESULT)"
            == run._analyze_result(normal_result, "", "memory")
        )

        run = self.create_run(info_result=RESULT_ERROR)
        run._is_timeout = lambda: True
        assert "TIMEOUT" == run._analyze_result(normal_result, "", "memory")

    def test_returnsignal(self):
        def signal(sig):
            """Encode a signal as it would be returned by os.wait"""
            return ProcessExitCode(raw=sig, value=None, signal=sig)

        run = self.create_run(info_result=RESULT_ERROR)
        assert "TIMEOUT" == run._analyze_result(signal(9), "", "cputime")

        run = self.create_run(info_result=RESULT_ERROR)
        assert (
            "OUT OF MEMORY"
            == run._analyze_result(signal(9), "", "memory")
        )

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        assert RESULT_TRUE_PROP == run._analyze_result(signal(9), "", None)

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        assert RESULT_FALSE_REACH == run._analyze_result(signal(9), "", None)

        run = self.create_run(info_result="SOME OTHER RESULT")
        assert (
            "SOME OTHER RESULT"
            == run._analyze_result(signal(9), "", None)
        )

        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert "KILLED BY SIGNAL 9" == run._analyze_result(signal(9), "", None)

    def test_exitcode(self):
        def returnvalue(value):
            """Encode an exit of a program as it would be returned by os.wait"""
            return ProcessExitCode(raw=value << 8, value=value, signal=None)

        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert "TIMEOUT" == run._analyze_result(returnvalue(1), "", "cputime")

        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert (
            "OUT OF MEMORY"
            == run._analyze_result(returnvalue(1), "", "memory")
        )

        run = self.create_run(info_result=RESULT_TRUE_PROP)
        assert RESULT_TRUE_PROP == run._analyze_result(returnvalue(1), "", None)

        run = self.create_run(info_result=RESULT_FALSE_REACH)
        assert RESULT_FALSE_REACH == run._analyze_result(returnvalue(1), "", None)

        run = self.create_run(info_result="SOME OTHER RESULT")
        assert (
            "SOME OTHER RESULT"
            == run._analyze_result(returnvalue(1), "", None)
        )

        run = self.create_run(info_result=RESULT_UNKNOWN)
        assert RESULT_UNKNOWN == run._analyze_result(returnvalue(1), "", None)
