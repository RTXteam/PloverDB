#!/usr/bin/env bash -x
set -euo pipefail

run_mypy_cmd="mypy --ignore-missing-imports"
run_ruff_cmd="ruff check"
run_vulture_cmd="vulture app/app/vulture_whitelist.py"
run_pylint_cmd="pylint"
files_to_check=(app/app/main.py
                app/app/plover.py
                app/app/build_indexes.py
                test/conftest.py)

for file in "${files_to_check[@]}"; do
    echo "Running ruff checks on file ${file}"
    ${run_ruff_cmd} ${file}

    echo "Running type checks on file ${file}"
    ${run_mypy_cmd} ${file}

    # Skip pylint for unit test modules in tests/ that start with test_
    if [[ ! "${file}" == tests/test_*.py ]]; then
        echo "Running pylint checks on file ${file}"
        ${run_pylint_cmd} "${file}" || true
    else
        echo "Skipping pylint for test file ${file}"
    fi    
done

echo "Running dead code checks"
${run_vulture_cmd} ${files_to_check}


echo "Running full pytest unit test suite"
pytest -v
